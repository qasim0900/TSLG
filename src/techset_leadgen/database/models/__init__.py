"""All ORM models; importing this package registers them on ``Base.metadata``."""

from techset_leadgen.database.models.audit import AuditLog
from techset_leadgen.database.models.identity import AuthAttempt, Organization, User, UserSession, UserToken
from techset_leadgen.database.models.meetings import Meeting, MeetingAttendee
from techset_leadgen.database.models.outreach import AssignmentBatch, Notification, OutreachEvent, Prospect, ProspectAssignment
from techset_leadgen.database.models.records import Activity, Client, Contact, Lead, LeadStatusChange, Task

__all__ = [
    "Activity",
    "AssignmentBatch",
    "AuditLog",
    "AuthAttempt",
    "Client",
    "Contact",
    "Lead",
    "LeadStatusChange",
    "Meeting",
    "MeetingAttendee",
    "Notification",
    "Organization",
    "OutreachEvent",
    "Prospect",
    "ProspectAssignment",
    "Task",
    "User",
    "UserSession",
    "UserToken",
]
