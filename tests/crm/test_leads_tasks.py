"""Leads (the one lead record shared with imports and funnel analytics) and tasks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from analysis.leads_analysis import get_funnel_stats
from crm.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from crm.models import AuditLog, Lead, LeadStatusChange
from crm.schemas import BulkAssignment, LeadCreate, LeadTransition, LeadUpdate, TaskUpdate, parse
from crm.services import leads, tasks, work
from crm.services.pagination import PageRequest
from crm.vocabulary import LEAD_STATUSES, LEAD_TRANSITIONS


def _move(db, actor, lead_id, status, reason=None, **extra):
    return leads.transition(db, actor, lead_id, parse(LeadTransition, {"status": status, "reason": reason}), **extra)


def test_imported_leads_join_the_workflow_without_any_conversion(db, world, acme):
    world.imported_client("C-1", "Acme Corp")
    lead_id = world.imported_lead("ext-42", source="google_ads", status="contacted", client_id="C-1")
    world.imported_lead("ext-43", source="tiktok_ads")
    lead = leads.get_lead(db, acme.actor(), lead_id)
    assert (lead.status, lead.priority, lead.version, lead.owner_id) == ("contacted", "medium", 1, None)
    assert leads.display_title(lead) == "Acme Corp (2026-09-01)"
    assert leads.display_title(leads.get_lead(db, acme.actor(), "ext-43")) == "TikTok Ads lead (2026-09-01)"
    assert set(leads.extras(db, acme.actor())) == {"ext-42", "ext-43"}


def test_a_manual_lead_starts_new_with_history_and_audit(db, world, acme):
    actor = acme.actor("bdr")
    lead = world.lead(actor, "Portal rebuild", meeting_date="2026-11-03", priority="high")
    assert lead.id.startswith("L_") and (lead.status, lead.priority, lead.meeting_date) == ("new", "high", "2026-11-03")
    assert lead.created_on == datetime.now(UTC).date().isoformat()  # the user's zone is UTC here
    assert db.scalar(select(LeadStatusChange.to_status).where(LeadStatusChange.lead_id == lead.id)) == "new"
    assert db.scalar(select(AuditLog.action).where(AuditLog.entity_id == lead.id)) == "lead.created"


def test_an_open_lead_for_the_same_client_is_flagged_but_can_be_added(db, world, acme):
    actor = acme.actor()
    client = world.client(actor, "Globex")
    world.lead(actor, "First", client=client)
    with pytest.raises(Conflict) as error:
        leads.create_lead(db, actor, parse(LeadCreate, {"title": "Second", "source": "manual_import",
                                                        "client_id": client.id}))
    assert error.value.details["existing_title"] == "First"
    db.rollback()
    leads.create_lead(db, actor, parse(LeadCreate, {"title": "Second", "source": "manual_import",
                                                    "client_id": client.id, "allow_duplicate": True}))


@pytest.mark.parametrize(("current", "target"), [(c, t) for c in LEAD_STATUSES for t in LEAD_STATUSES if c != t])
def test_stage_moves_follow_the_documented_transitions(db, world, acme, current, target):
    actor = acme.actor()
    client = world.client(actor, "Client Co")
    lead_id = world.imported_lead(f"L-{current}-{target}", status=current, client_id=client.id)
    allowed = target in LEAD_TRANSITIONS[current]
    try:
        _move(db, actor, lead_id, target, reason="Because")
    except Conflict:
        assert not allowed
    else:
        assert allowed
        assert db.get(Lead, lead_id).status == target


def test_qualifying_or_losing_a_lead_needs_a_reason_which_is_kept(db, world, acme):
    actor = acme.actor()
    lead = world.lead(actor, "Shop")
    with pytest.raises(ValidationFailed) as error:
        _move(db, actor, lead.id, "qualified")
    assert error.value.fields == {"reason": "A reason is required for this stage."}
    _move(db, actor, lead.id, "qualified", "Budget approved")
    _move(db, actor, lead.id, "lost", "Chose a competitor")
    db.commit()
    stored = db.get(Lead, lead.id)
    assert (stored.qualification_reason, stored.lost_reason) == ("Budget approved", "Chose a competitor")
    history = [(row.from_status, row.to_status, row.reason) for row in leads.status_history(db, actor, stored)]
    assert history[:2] == [("qualified", "lost", "Chose a competitor"), ("new", "qualified", "Budget approved")]


def test_marking_a_lead_client_requires_a_linked_client_and_meetings_get_their_date(db, world, acme):
    actor = acme.actor()
    lead = world.lead(actor, "No client yet")
    _move(db, actor, lead.id, "meeting", meeting_date="2026-12-01")
    assert db.get(Lead, lead.id).meeting_date == "2026-12-01"
    with pytest.raises(ValidationFailed, match="Link the lead to a client"):
        _move(db, actor, lead.id, "converted")
    client = world.client(actor, "Now Linked")
    leads.update_lead(db, actor, lead.id, parse(LeadUpdate, {"client_id": client.id}))
    _move(db, actor, lead.id, "converted")
    with pytest.raises(ValidationFailed, match="must stay linked"):
        leads.update_lead(db, actor, lead.id, parse(LeadUpdate, {"client_id": None}))


def test_roles_limit_who_edits_qualifies_and_assigns(db, world, acme):
    researcher_lead = world.lead(acme.actor("lead_researcher"), "Found by research")
    with pytest.raises(PermissionDenied):  # researchers add leads but do not qualify them
        _move(db, acme.actor("lead_researcher"), researcher_lead.id, "qualified", "Looks good")
    imported = world.imported_lead("ext-1")
    with pytest.raises(PermissionDenied):  # unassigned imported leads belong to nobody yet
        leads.update_lead(db, acme.actor("bdr"), imported, parse(LeadUpdate, {"priority": "high"}))
    leads.assign(db, acme.actor("bdr"), imported, acme.users["bdr"].id)  # ...but a rep may take one
    leads.update_lead(db, acme.actor("bdr"), imported, parse(LeadUpdate, {"priority": "high"}))
    with pytest.raises(PermissionDenied):  # and cannot hand it to someone else
        leads.assign(db, acme.actor("bdr"), imported, acme.users["account_executive"].id)
    with pytest.raises(PermissionDenied):
        leads.update_lead(db, acme.actor("account_executive"), imported, parse(LeadUpdate, {"notes": "x"}))
    for role in ("marketing", "read_only"):
        with pytest.raises(PermissionDenied):
            leads.create_lead(db, acme.actor(role), parse(LeadCreate, {"title": "x", "source": "manual_import"}))
    unclaimed = world.imported_lead("ext-2")
    for role in ("marketing", "read_only"):  # roles that do not work leads cannot take one either
        with pytest.raises(PermissionDenied):
            leads.assign(db, acme.actor(role), unclaimed, acme.users[role].id)


def test_bulk_assignment_is_all_or_nothing(db, world, acme):
    manager = acme.actor("sales_manager")
    ids = [world.imported_lead(f"bulk-{n}") for n in range(3)]
    owner = acme.users["account_executive"].id
    with pytest.raises(NotFound):
        leads.bulk_assign(db, manager, parse(BulkAssignment, {"lead_ids": [*ids, "missing"], "owner_id": owner}))
    db.rollback()
    assert leads.bulk_assign(db, manager, parse(BulkAssignment, {"lead_ids": ids, "owner_id": owner})) == 3
    db.commit()
    assert {db.get(Lead, lead_id).owner_id for lead_id in ids} == {owner}
    with pytest.raises(PermissionDenied):
        leads.bulk_assign(db, acme.actor("bdr"), parse(BulkAssignment, {"lead_ids": ids, "owner_id": None}))


def test_timeline_merges_activities_stage_changes_and_edits(db, world, acme):
    actor = acme.actor()
    lead = world.lead(actor, "Timeline")
    world.activity(actor, lead_id=lead.id, subject="Discovery call")
    _move(db, actor, lead.id, "contacted")
    leads.update_lead(db, actor, lead.id, parse(LeadUpdate, {"priority": "urgent"}))
    leads.assign(db, actor, lead.id, acme.users["bdr"].id)
    db.commit()
    titles = [entry.title for entry in leads.timeline(db, actor, db.get(Lead, lead.id))]
    assert "Discovery call" in titles and "Stage: Lead → Contacted" in titles and "Lead created" in titles
    assert "Edited priority" in titles and any(title.startswith("Assigned to") for title in titles)


def test_follow_up_tasks_set_the_lead_follow_up_and_feed_my_work(db, world, acme):
    actor = acme.actor("bdr")
    lead = world.lead(actor, "Needs a call", owner_id=actor.user_id)  # as the New lead form does
    soon = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    later = soon + timedelta(days=3)
    first = world.task(actor, "Call", lead_id=lead.id, due_at=soon.isoformat())
    world.task(actor, "Send proposal", lead_id=lead.id, due_at=later.isoformat())
    db.expire_all()
    assert db.get(Lead, lead.id).next_follow_up_at == soon
    tasks.set_status(db, actor, first.id, "done")
    db.commit()
    assert db.get(Lead, lead.id).next_follow_up_at == later
    world.task(actor, "Overdue chore", due_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
    summary = work.summary(db, actor)
    assert (summary.open_tasks, summary.overdue, summary.my_open_leads) == (2, 1, 1)


def test_task_visibility_and_editing_follow_roles(db, world, acme):
    manager_task = world.task(acme.actor("sales_manager"), "Manager only")
    bdr = acme.actor("bdr")
    with pytest.raises(NotFound):
        tasks.get_task(db, bdr, manager_task.id)
    with pytest.raises(PermissionDenied):
        tasks.list_tasks(db, bdr, page=PageRequest(), view="team")
    assert tasks.list_tasks(db, acme.actor("read_only"), page=PageRequest(), view="team").total == 1
    own = world.task(bdr, "Mine")
    tasks.update_task(db, bdr, own.id, parse(TaskUpdate, {"priority": "high"}))
    with pytest.raises(PermissionDenied):
        tasks.update_task(db, acme.actor("read_only"), own.id, parse(TaskUpdate, {"priority": "low"}))


def test_the_funnel_counts_qualified_leads_as_past_the_meeting_stage():
    stats = get_funnel_stats([{"status": status, "created_at": "2026-01-01"}
                              for status in ("new", "contacted", "meeting", "qualified", "nurture", "converted", "lost")])
    assert (stats["total"], stats["meetings"], stats["converted"], stats["lost"]) == (7, 3, 1, 1)
