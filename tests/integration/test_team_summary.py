from __future__ import annotations

from datetime import UTC, datetime, timedelta

from techset_leadgen.database.models import Prospect, ProspectAssignment, Task
from techset_leadgen.services import team


def test_manager_and_member_summaries_use_stored_work(db, acme):
    manager = acme.actor("sales_manager")
    member = acme.users["bdr"]
    other = acme.users["account_executive"]
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    first = Prospect(linkedin_key="in/one", linkedin_url="https://www.linkedin.com/in/one/",
                     full_name="One Person", status="new", created_by_id=manager.user_id)
    second = Prospect(linkedin_key="in/two", linkedin_url="https://www.linkedin.com/in/two/",
                      full_name="Two Person", status="new", created_by_id=manager.user_id)
    third = Prospect(linkedin_key="in/three", linkedin_url="https://www.linkedin.com/in/three/",
                     full_name="Three Person", status="new", created_by_id=manager.user_id)
    db.add_all((first, second, third))
    db.flush()
    db.add_all((
        ProspectAssignment(prospect_id=first.id, assignee_id=member.id, assigned_by_id=manager.user_id,
                           status="assigned", assigned_at=now - timedelta(hours=2)),
        ProspectAssignment(prospect_id=second.id, assignee_id=other.id, assigned_by_id=manager.user_id,
                           status="completed", assigned_at=now - timedelta(hours=3),
                           closed_at=now - timedelta(hours=1)),
        Task(title="Member follow-up", kind="follow_up", prospect_id=first.id, assigned_to_id=member.id,
             priority="medium", due_at=now - timedelta(hours=1), status="open", created_by_id=manager.user_id),
        Task(title="Other general task", kind="task", assigned_to_id=other.id, priority="high",
             due_at=now - timedelta(hours=1), status="open", created_by_id=manager.user_id),
    ))
    db.commit()

    manager_view = team.summary(db, manager, now=now)
    assert (manager_view.assigned_today, manager_view.completed_today,
            manager_view.outstanding_assignments, manager_view.unassigned_prospects) == (2, 1, 1, 2)
    assert (manager_view.pending_follow_ups, manager_view.overdue_follow_ups,
            manager_view.overdue_tasks) == (1, 1, 1)
    member_view = team.summary(db, acme.actor("bdr"), now=now)
    assert (member_view.assigned_today, member_view.completed_today,
            member_view.outstanding_assignments, member_view.unassigned_prospects) == (1, 0, 1, 0)
    assert (member_view.pending_follow_ups, member_view.overdue_follow_ups,
            member_view.overdue_tasks) == (1, 1, 0)
    assert member_view.workload == ()

