"""Common notification data structures for all flows (MBA/MBU/MSO).

This module intentionally keeps the core domain model very small and stable
and separates it from presentation (templates) and delivery channels.

It can be introduced without changing existing queue payloads by using
adapters/serializers in each flow strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Flow(Enum):
    MBA = "MBA"
    MBU = "MBU"
    MSO = "MSO"


class Channel(Enum):
    EMAIL = "email"
    DIGITAL_POST = "digital_post"


class Audience(Enum):
    SUPERVISOR = "supervisor"
    EMPLOYEE = "employee"


@dataclass(frozen=True)
class Recipient:
    """Generic recipient for a notification.

    - audience: who is the recipient (supervisor/employee)
    - channel: which delivery channel (email/digital_post)
    - address: for EMAIL this is an email address; for DIGITAL_POST this is CPR
    """
    audience: Audience
    channel: Channel
    address: str | None


@dataclass(frozen=True)
class Notification:
    """Concrete message to be sent via a channel.

    - flow: the originating flow (MBA/MBU/MSO)
    - recipient: who and how to send
    - template_id: identifier used to resolve the message template
    - render_context: dict with variables for templating
    - reference: queue element reference (unique per element in orchestrator)
    - queue_name: which orchestrator queue to use
    """
    flow: Flow
    recipient: Recipient
    template_id: str
    render_context: dict[str, Any]
    reference: str
    queue_name: str
