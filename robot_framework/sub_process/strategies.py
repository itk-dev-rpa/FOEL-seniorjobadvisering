"""Strategy layer scaffolding for MBA/MBU/MSO flows.

This module defines a common strategy interface and an initial MBA strategy
that can be used to plan notifications while keeping current queue payloads
unchanged. Wiring existing modules to these strategies can be done
incrementally in follow-up changes.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from abc import ABC, abstractmethod
from typing import Iterable

from itk_dev_shared_components.misc import cpr_util

from robot_framework import config
from robot_framework.sub_process.models import Supervisor
from robot_framework.sub_process.notifications import (
    Notification,
    Recipient,
    Audience,
    Channel,
    Flow,
)


class FlowStrategy(ABC):
    flow: Flow

    @abstractmethod
    def select_periods(self) -> list[tuple[date, date]]:
        """Return one or more periods to evaluate for this flow."""
        raise NotImplementedError

    @abstractmethod
    def find_people(self, start_date: date, end_date: date) -> list[Supervisor]:
        """Resolve supervisors (with employees) in the given period."""
        raise NotImplementedError

    @abstractmethod
    def plan_notifications(self, supervisors: Iterable[Supervisor]) -> list[Notification]:
        """Map supervisors/employees to notifications (no side effects)."""
        raise NotImplementedError

    @abstractmethod
    def serialize(self, n: Notification) -> dict:
        """Build the queue payload for the given notification.

        IMPORTANT: This keeps existing queue contracts intact to avoid
        breaking changes during incremental migration.
        """
        raise NotImplementedError


# --- MBA strategy scaffold -------------------------------------------------

# We deliberately import inside methods to avoid import cycles during refactor.
class MbaStrategy(FlowStrategy):
    flow = Flow.MBA

    def select_periods(self) -> list[tuple[date, date]]:
        from robot_framework.sub_process.mba import get_period  # local import
        ages = (55, 60, 63, 65, 70)
        return [get_period(age) for age in ages]

    def find_people(self, start_date: date, end_date: date) -> list[Supervisor]:
        from robot_framework.sub_process.mba import get_people  # local import
        return get_people(start_date, end_date)

    def plan_notifications(self, supervisors: Iterable[Supervisor]) -> list[Notification]:
        notifications: list[Notification] = []

        for s in supervisors:
            # Supervisor mail: Keep batching per supervisor to mirror current approach
            employees_payload = [
                {"name": e.name, "age": cpr_util.get_age(e.cpr)} for e in s.employees
            ]
            notifications.append(
                Notification(
                    flow=self.flow,
                    recipient=Recipient(
                        audience=Audience.SUPERVISOR,
                        channel=Channel.EMAIL,
                        address=s.email,
                    ),
                    template_id="mba_supervisor_mixed_by_age",  # resolved at send-time
                    render_context={
                        "name": s.name,
                        "email": s.email,
                        "employees": employees_payload,
                    },
                    reference=f"{s.email}",
                    queue_name=config.MBA_QUEUE_SUPERVISOR,
                )
            )

            # Employee mails: one per employee, age-dependent template chosen at send-time
            for e in s.employees:
                notifications.append(
                    Notification(
                        flow=self.flow,
                        recipient=Recipient(
                            audience=Audience.EMPLOYEE,
                            channel=Channel.EMAIL,
                            address=e.email,
                        ),
                        template_id="mba_employee_by_age",
                        render_context={
                            "cpr": e.cpr,
                            "name": e.name,
                            "email": e.email,
                        },
                        reference=e.cpr,
                        queue_name=config.MBA_QUEUE_EMPLOYEE,
                    )
                )

        return notifications

    def serialize(self, n: Notification) -> dict:
        # Preserve existing MBA queue payload shapes
        if n.queue_name == config.MBA_QUEUE_SUPERVISOR:
            # Matches Supervisor.to_dict_mba() structure
            return {
                "name": n.render_context.get("name"),
                "email": n.render_context.get("email"),
                "employees": list(n.render_context.get("employees", [])),
            }
        if n.queue_name == config.MBA_QUEUE_EMPLOYEE:
            # Matches Employee.to_dict() structure
            return {
                "cpr": n.render_context.get("cpr"),
                "name": n.render_context.get("name"),
                "email": n.render_context.get("email"),
            }
        # Default: return context as-is
        return dict(n.render_context)


class MbuStrategy(FlowStrategy):
    flow = Flow.MBU

    def select_periods(self) -> list[tuple[date, date]]:
        from robot_framework.sub_process.mbu import get_period  # local import
        return [get_period()]

    def find_people(self, start_date: date, end_date: date) -> list[Supervisor]:
        from robot_framework.sub_process.mbu import get_people  # local import
        return get_people(start_date, end_date)

    def plan_notifications(self, supervisors: Iterable[Supervisor]) -> list[Notification]:
        notifications: list[Notification] = []
        for s in supervisors:
            # Supervisor email: one per supervisor with list of employee strings
            employees_strings = [e.to_mail_string() for e in s.employees]
            notifications.append(
                Notification(
                    flow=self.flow,
                    recipient=Recipient(
                        audience=Audience.SUPERVISOR,
                        channel=Channel.EMAIL,
                        address=s.email,
                    ),
                    template_id="mbu_supervisor_email",
                    render_context={
                        "name": s.name,
                        "email": s.email,
                        "employees": employees_strings,
                    },
                    reference=f"{s.email}",
                    queue_name=getattr(config, "MBU_QUEUE_SUPERVISOR"),
                )
            )
            # Employee digital post: one per employee
            for e in s.employees:
                notifications.append(
                    Notification(
                        flow=self.flow,
                        recipient=Recipient(
                            audience=Audience.EMPLOYEE,
                            channel=Channel.DIGITAL_POST,
                            address=e.cpr,
                        ),
                        template_id="mbu_employee_digital_post",
                        render_context={
                            "cpr": e.cpr,
                            "name": e.name,
                            "email": e.email,
                        },
                        reference=e.cpr,
                        queue_name=getattr(config, "MBU_QUEUE_EMPLOYEE"),
                    )
                )
        return notifications

    def serialize(self, n: Notification) -> dict:
        # Preserve existing MBU queue payload shapes
        if n.queue_name == getattr(config, "MBU_QUEUE_SUPERVISOR"):
            # Matches Supervisor.to_dict() structure (employees as strings)
            return {
                "name": n.render_context.get("name"),
                "email": n.render_context.get("email"),
                "employees": list(n.render_context.get("employees", [])),
            }
        if n.queue_name == getattr(config, "MBU_QUEUE_EMPLOYEE"):
            # Matches Employee.to_dict() structure
            return {
                "cpr": n.render_context.get("cpr"),
                "name": n.render_context.get("name"),
                "email": n.render_context.get("email"),
            }
        return dict(n.render_context)


class MsoStrategy(FlowStrategy):
    flow = Flow.MSO

    def select_periods(self) -> list[tuple[date, date]]:
        from robot_framework.sub_process.mso import get_period  # local import
        return [get_period()]

    def find_people(self, start_date: date, end_date: date) -> list[Supervisor]:
        from robot_framework.sub_process.mso import get_people  # local import
        return get_people(start_date, end_date)

    def plan_notifications(self, supervisors: Iterable[Supervisor]) -> list[Notification]:
        notifications: list[Notification] = []
        for s in supervisors:
            employees_strings = [e.to_mail_string() for e in s.employees]
            notifications.append(
                Notification(
                    flow=self.flow,
                    recipient=Recipient(
                        audience=Audience.SUPERVISOR,
                        channel=Channel.EMAIL,
                        address=s.email,
                    ),
                    template_id="mso_supervisor_email",
                    render_context={
                        "name": s.name,
                        "email": s.email,
                        "employees": employees_strings,
                    },
                    reference=f"{s.email}",
                    queue_name=getattr(config, "MSO_QUEUE_SUPERVISOR"),
                )
            )
            for e in s.employees:
                notifications.append(
                    Notification(
                        flow=self.flow,
                        recipient=Recipient(
                            audience=Audience.EMPLOYEE,
                            channel=Channel.DIGITAL_POST,
                            address=e.cpr,
                        ),
                        template_id="mso_employee_digital_post",
                        render_context={
                            "cpr": e.cpr,
                            "name": e.name,
                            "email": e.email,
                        },
                        reference=e.cpr,
                        queue_name=getattr(config, "MSO_QUEUE_EMPLOYEE"),
                    )
                )
        return notifications

    def serialize(self, n: Notification) -> dict:
        if n.queue_name == getattr(config, "MSO_QUEUE_SUPERVISOR"):
            return {
                "name": n.render_context.get("name"),
                "email": n.render_context.get("email"),
                "employees": list(n.render_context.get("employees", [])),
            }
        if n.queue_name == getattr(config, "MSO_QUEUE_EMPLOYEE"):
            return {
                "cpr": n.render_context.get("cpr"),
                "name": n.render_context.get("name"),
                "email": n.render_context.get("email"),
            }
        return dict(n.render_context)


def known_queues_for(flow: Flow) -> tuple[str, ...]:
    if flow is Flow.MBA:
        return (config.MBA_QUEUE_SUPERVISOR, config.MBA_QUEUE_EMPLOYEE)
    if flow is Flow.MBU:
        return (getattr(config, "MBU_QUEUE_SUPERVISOR", ""), getattr(config, "MBU_QUEUE_EMPLOYEE", ""))
    if flow is Flow.MSO:
        return (getattr(config, "MSO_QUEUE_SUPERVISOR", ""), getattr(config, "MSO_QUEUE_EMPLOYEE", ""))
    return tuple()
