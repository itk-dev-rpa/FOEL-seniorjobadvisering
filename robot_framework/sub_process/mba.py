"""This module contains the process for MBA."""

import calendar
from datetime import date
import json

import pyodbc

from itk_dev_shared_components.misc import cpr_util
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus

from robot_framework import config
from robot_framework.sub_process.models import Supervisor, Employee
from robot_framework.sub_process.senders.email_sender import EmailSender, EmailConfig


def get_period(age: int) -> tuple[date, date]:
    """Calculate the period we want to look up.
    The period is always the previous month 58 years ago.

    Args:
        age: The age of the employees to look for.

    Returns:
        A tuple of the period start and end date.
    """
    today = date.today()

    if today.month == 1:
        previous_month = 12
        year = today.year - 1
    else:
        previous_month = today.month - 1
        year = today.year

    year -= age
    start_date = date(year, previous_month, 1)

    _, end_day = calendar.monthrange(year, previous_month)
    end_date = date(year, previous_month, end_day)

    return start_date, end_date


def get_people(start_date: date, end_date: date) -> list[Supervisor]:
    """Get a list of supervisors and their employees who should be notified.

    Args:
        start_date: The start date to search for employee birthdays.
        end_date: The end date to search for employee birthdays.

    Returns:
        A list of Supervisor objects with employees who's birthdays are in the given range.
    """
    connection = pyodbc.connect("Server=FaellesSQL;Database=Personale;Trusted_Connection=yes;Driver={ODBC Driver 17 for SQL Server}")
    cursor = connection.cursor()

    cursor.execute(
        """SELECT
            a.CPR,
            a.Tjenestenummer,
            a.Email,
            a.Stilling,
            b.FungPersLederKaldeNavn,
            b.KaldeNavn,
            d.FungerendeLederEmail

        FROM [Personale].[sd_magistrat].[Ansættelse_udvidet_alle] AS a
        JOIN [ORG].[adm].[Bruger_Personaleleder] AS b ON a.Brugernavn = b.Brugernavn
        JOIN [ORG].[LØN].[LønOrgEnhed_Aktuel] AS c ON a.Afdeling = c.SdAfdId
        JOIN [ORG].[adm].[OrgEnhed_Aktuel_Leder] AS d ON b.FungPersLederBrugerNavn = d.LederBrugernavn

        WHERE
            a.PrimærAnsættelse_Aktuel = 1
            AND a.Deltidsbeskæftigelseskode IN (0, 1)
            AND c.MagAfdID = 'BA'
            AND CONVERT(date, STUFF(STUFF(SUBSTRING(a.CPR, 1, 6), 5, 0, '.'), 3, 0, '.'), 4) BETWEEN ? AND ?""",
        start_date,
        end_date
    )

    supervisors: dict[str, Supervisor] = {}
    for row in cursor:
        cpr, employee_number, email, occupation, supervisor_name, name, supervisor_email = row

        if supervisor_email not in supervisors:
            supervisors[supervisor_email] = Supervisor(supervisor_name, supervisor_email)

        supervisors[supervisor_email].employees.append(
            Employee(
                cpr=cpr,
                name=name,
                number=employee_number,
                occupation=occupation.strip(),
                birthday=cpr_util.get_birth_date(cpr).strftime("%d/%m/%Y"),
                email=email
            )
        )

    return list(supervisors.values())


def send_mails_to_supervisor(supervisor: dict):
    """Send emails to the given supervisor for each of
    their employees in the list.

    Args:
        supervisor: A dictionary as made by Supervisor.to_dict_mba.
    """
    email = EmailSender(EmailConfig(smtp_server=config.SMTP_SERVER, smtp_port=config.SMTP_PORT))

    for employee in supervisor["employees"]:
        # Choose template based on age (<63 vs >=63) – same as before
        if employee["age"] < 63:
            template_path = "message_texts/mba/mail_supervisor_under_63.html"
        else:
            template_path = "message_texts/mba/mail_supervisor_over_63.html"

        context = {
            "LederNavn": supervisor["name"],
            "MedarbejderNavn": employee["name"],
        }

        email.send_from_template(
            template_path=template_path,
            context=context,
            receiver=supervisor["email"],
            sender=config.MBA_MAIL_SENDER,
            subject="Din medarbejder skal indkaldes til seniorsamtale",
        )


def send_mails_to_employee(employee: dict):
    """Send an email to the given employee.

    Args:
        supervisor: A dictionary as made by Employee.to_dict.
    """
    email = EmailSender(EmailConfig(smtp_server=config.SMTP_SERVER, smtp_port=config.SMTP_PORT))

    # Choose template based on age (<63 vs >=63) – same as before
    if cpr_util.get_age(employee["cpr"]) < 63:
        template_path = "message_texts/mba/mail_employee_under_63.html"
    else:
        template_path = "message_texts/mba/mail_employee_over_63.html"

    context = {
        "Navn": employee["name"],
    }

    email.send_from_template(
        template_path=template_path,
        context=context,
        receiver=employee["email"],
        sender=config.MBA_MAIL_SENDER,
        subject="Tilbud om seniorsamtale",
    )


def append_queue(orchestrator_connection: OrchestratorConnection):
    """Find people who should be notified and add them to the orchestrator queues.

    Uses the MbaStrategy to plan notifications, while preserving existing
    queue payloads and reference formats (including period date for
    supervisor references).

    Args:
        orchestrator_connection: The connection to orchestrator.
    """
    from robot_framework.sub_process.strategies import MbaStrategy
    from robot_framework.sub_process.orchestration import append_via_strategy

    strategy = MbaStrategy()

    def format_reference(n, start_date):
        if n.queue_name == config.MBA_QUEUE_SUPERVISOR:
            return f"{n.recipient.address} - {start_date.strftime('%d/%m/%Y')}"
        return n.reference

    append_via_strategy(orchestrator_connection, strategy, format_reference)


def handle_queue(orchestrator_connection: OrchestratorConnection):
    """Handle any queue elements in the two orchestrator queues.

    Args:
        orchestrator_connection: The connection to orchestrator.
    """
    from robot_framework.sub_process.orchestration import process_queue

    # Handle supervisor emails (unified logging)
    process_queue(
        orchestrator_connection,
        queue_name=config.MBA_QUEUE_SUPERVISOR,
        handle_item=lambda d: send_mails_to_supervisor(d),
        flow_label="MBA",
        extract_meta=lambda d: (
            "email",
            d.get("email", "n/a"),
            "message_texts/mba/mail_supervisor_{age_bucket}.html".format(
                age_bucket="mixed_by_age"
            ),
        ),
    )

    # Handle employee emails (unified logging)
    process_queue(
        orchestrator_connection,
        queue_name=config.MBA_QUEUE_EMPLOYEE,
        handle_item=lambda d: send_mails_to_employee(d),
        flow_label="MBA",
        extract_meta=lambda d: (
            "email",
            d.get("email", "n/a"),
            "message_texts/mba/mail_employee_{}63.html".format(
                "under_" if cpr_util.get_age(d.get("cpr", "")) < 63 else "over_"
            ),
        ),
    )
