"""This module contains the process for MSO."""

import calendar
from datetime import date
import json

import pyodbc
from python_serviceplatformen.models.message import Sender
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.misc import cpr_util
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus

from robot_framework import config
from robot_framework.sub_process.models import Supervisor, Employee
from robot_framework.sub_process.senders.email_sender import EmailSender, EmailConfig
from robot_framework.sub_process.senders.digital_post_sender import DigitalPostSender


def get_period() -> tuple[date, date]:
    """Calculate the period we want to look up.
    The period is always the previous month 58 years ago.

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

    year -= 58
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
        """
        SELECT
            a.[CPR],
            a.[Tjenestenummer], a.[Stilling],
            b.[FungPersLederKaldeNavn], b.[KaldeNavn],
            d.[FungerendeLederEmail]
        FROM
            [Personale].[sd_magistrat].[Ansættelse_udvidet_alle] AS a
            JOIN [ORG].[adm].[Bruger_Personaleleder] AS b ON a.Brugernavn = b.Brugernavn
            JOIN [ORG].[LØN].[LønOrgEnhed_Aktuel] AS c ON a.afdeling = c.SdAfdId
            JOIN [ORG].[adm].[OrgEnhed_Aktuel_Leder] AS d ON b.[FungPersLederBrugerNavn]=d.[LederBrugernavn]
        WHERE
            a.PrimærAnsættelse_Aktuel = 1
            AND a.Deltidsbeskæftigelseskode IN(0,1)
            AND c.MagAfdID='MSO'
            AND CONVERT(datetime, STUFF(STUFF(SUBSTRING(a.CPR,0,7),5,0,'.'),3,0,'.'), 4) BETWEEN ? AND ?""",
        start_date,
        end_date
    )

    supervisors: dict[str, Supervisor] = {}
    for row in cursor:
        cpr, employee_number, occupation, supervisor_name, name, supervisor_email = row

        if supervisor_email not in supervisors:
            supervisors[supervisor_email] = Supervisor(supervisor_name, supervisor_email)

        supervisors[supervisor_email].employees.append(
            Employee(
                cpr=cpr,
                name=name,
                number=employee_number,
                occupation=occupation.strip(),
                birthday=cpr_util.get_birth_date(cpr).strftime("%d/%m/%Y")
            )
        )

    return list(supervisors.values())


def send_mail_to_supervisor(supervisor: dict):
    """Send an email to the given supervisor."""
    email = EmailSender(EmailConfig(smtp_server=config.SMTP_SERVER, smtp_port=config.SMTP_PORT))

    employee_strings = [f"<li>{w}</li>" for w in supervisor["employees"]]
    context = {
        "LederNavn": supervisor["name"],
        "MedarbejderNavne": "\n".join(employee_strings),
    }

    email.send_from_template(
        template_path="message_texts/mso/mso_supervisor_email_text.html",
        context=context,
        receiver=supervisor["email"],
        sender=config.MSO_MAIL_SENDER,
        subject="Din medarbejder skal indkaldes til seniorsamtale",
    )


def send_digital_post_to_employee(cpr: str, name: str, kombit_access: KombitAccess):
    """Send Digital Post to the given employee.

    Args:
        cpr: Cpr of the employee.
        name: Name of the employee
        kombit_access: KombitAccess object used for authentication.
    """
    sender = Sender(senderID="55133018", idType="CVR", label="Aarhus Kommune")
    context = {
        "Navn": name,
        "År": str(cpr_util.get_age(cpr)),
    }

    dp = DigitalPostSender()
    dp.send_from_template(
        template_path="message_texts/mso/mso_employee_digital_post_text.html",
        context=context,
        recipient_cpr=cpr,
        sender=sender,
        subject="Tilbud om seniorsamtale",
        kombit_access=kombit_access,
    )


def append_queue(orchestrator_connection: OrchestratorConnection):
    """Find people who should be notified and add them to the orchestrator queues.

    Uses the MsoStrategy to plan notifications, while preserving existing
    queue payloads and reference formats (including period date for
    supervisor references).

    Args:
        orchestrator_connection: The connection to orchestrator.
    """
    from robot_framework.sub_process.strategies import MsoStrategy
    from robot_framework.sub_process.orchestration import append_via_strategy

    strategy = MsoStrategy()

    def format_reference(n, start_date):
        if n.queue_name == config.MSO_QUEUE_SUPERVISOR:
            return f"{n.recipient.address} - {start_date.strftime('%d/%m/%Y')}"
        return n.reference

    append_via_strategy(orchestrator_connection, strategy, format_reference)


def handle_queue(orchestrator_connection: OrchestratorConnection, kombit_access: KombitAccess):
    """Handle any queue elements in the two orchestrator queues.

    Args:
        orchestrator_connection: The connection to orchestrator.
        kombit_access: KombitAccess object used for authentication.
    """
    from robot_framework.sub_process.orchestration import process_queue

    # Handle supervisor emails (unified logging)
    process_queue(
        orchestrator_connection,
        queue_name=config.MSO_QUEUE_SUPERVISOR,
        handle_item=lambda d: send_mail_to_supervisor(d),
        flow_label="MSO",
        extract_meta=lambda d: (
            "email",
            d.get("email", "n/a"),
            "message_texts/mso/mso_supervisor_email_text.html",
        ),
    )

    # Handle employee Digital Post (unified logging)
    process_queue(
        orchestrator_connection,
        queue_name=config.MSO_QUEUE_EMPLOYEE,
        handle_item=lambda d: send_digital_post_to_employee(d["cpr"], d["name"], kombit_access),
        flow_label="MSO",
        extract_meta=lambda d: (
            "digital_post",
            d.get("cpr", "n/a"),
            "message_texts/mso/mso_employee_digital_post_text.html",
        ),
    )
