"""This module contains the process for MBU."""

import base64
from datetime import date
import calendar
from io import BytesIO
import json

import pyodbc
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus
from python_serviceplatformen.models.message import create_digital_post_with_main_document, Sender, Recipient, File
from python_serviceplatformen import digital_post
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.smtp import smtp_util
from itk_dev_shared_components.misc import cpr_util

from robot_framework import config
from robot_framework.sub_process.models import Supervisor, Employee
from robot_framework.sub_process.senders.email_sender import EmailSender, EmailConfig
from robot_framework.sub_process.senders.digital_post_sender import DigitalPostSender


def get_period() -> tuple[date, date]:
    """Calculate the period we want to look up.
    The period is always the previous quarter 58 years ago.

    Returns:
        A tuple of the period start and end date.
    """
    today = date.today()

    current_quarter = (today.month - 1) // 3 + 1

    if current_quarter == 1:
        prev_quarter = 4
        year = today.year - 1
    else:
        prev_quarter = current_quarter - 1
        year = today.year

    start_month = (prev_quarter - 1) * 3 + 1
    end_month = start_month + 2

    year -= 58
    start_date = date(year, start_month, 1)

    _, end_day = calendar.monthrange(year, end_month)
    end_date = date(year, end_month, end_day)

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
        SELECT DISTINCT
            a.[CPR], a.[Tjenestenummer], a.[Stilling],
            b.[FungPersLederKaldeNavn], b.[KaldeNavn],
            d.[FungerendeLederEmail]

        From [Personale].[sd_magistrat].[Ansættelse_udvidet_alle] AS a
            Join [ORG].[adm].[Bruger_Personaleleder]            AS b ON a.Brugernavn = b.Brugernavn
            Join [ORG].[LØN].[LønOrgEnhed_Aktuel]               AS c ON a.afdeling = c.SdAfdId
            Join [ORG].[adm].[OrgEnhed_Aktuel_Leder]            AS d ON b.[FungPersLederBrugerNavn] = d.[LederBrugernavn]
            Join [Personale].[sd_magistrat].[Ansættelse_alle]   AS e ON a.[AnsættelsesId] = e.[AnsættelsesId]

        Where a.PrimærAnsættelse_Aktuel = 1
            AND a.Deltidsbeskæftigelseskode IN(0,1)
            AND a.Institutionskode in ('XA','XD')
            AND e.Overenskomst IN(46001, 46002, 46101, 76001, 76101, 46004, 46901)
            AND e.Stillingskode<>3037
            AND c.MagAfdID='MBU'
            AND CONVERT(datetime, Stuff(Stuff(SUBSTRING(a.CPR,0,7),5,0,'.'),3,0,'.'), 4) BETWEEN ? And ?
            AND (c.Niv5_SDafdId='5F4A' or c.Niv4_SDafdId='5F7A' or c.Niv4_SDafdId='5Z6Q' or c.Niv5_SDafdId='5F4A')""",

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
    """Send an email to the given supervisor with a list of their
    employees who have turned 58.

    Args:
        supervisor: A dictionary as made by Supervisor.to_dict.
    """
    # Render HTML from existing template using EmailSender (parity with previous logic)
    email = EmailSender(EmailConfig(smtp_server=config.SMTP_SERVER, smtp_port=config.SMTP_PORT))

    # Build the HTML list items for employees and pass as a single string to template
    employee_strings = [f"<li>{w}</li>" for w in supervisor["employees"]]
    context = {
        "LederNavn": supervisor["name"],
        "MedarbejderNavne": "\n".join(employee_strings),
    }

    # Prepare PDF attachment identical to previous behavior
    with open("message_texts/attachments/Den gode seniorsamtale_Advis_leder.pdf", "rb") as pdf_file:
        pdf_bytes = BytesIO(pdf_file.read())
    attachment = smtp_util.EmailAttachment(file=pdf_bytes, file_name="Den gode seniorsamtale_Advis_leder.pdf")

    email.send_from_template(
        template_path="message_texts/mbu/mbu_supervisor_email_text.html",
        context=context,
        receiver=supervisor["email"],
        sender=config.MBU_MAIL_SENDER,
        subject="Din medarbejder skal indkaldes til seniorsamtale",
        attachments=[attachment],
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
        template_path="message_texts/mbu/mbu_digital_post.html",
        context=context,
        recipient_cpr=cpr,
        sender=sender,
        subject="Tilbud om seniorsamtale",
        kombit_access=kombit_access,
    )


def append_queue(orchestrator_connection: OrchestratorConnection):
    """Find people who should be notified and add them to the orchestrator queues.

    Uses the MbuStrategy to plan notifications, while preserving existing
    queue payloads and reference formats (including period date for
    supervisor references).

    Args:
        orchestrator_connection: The connection to orchestrator.
    """
    from robot_framework.sub_process.strategies import MbuStrategy
    from robot_framework.sub_process.orchestration import append_via_strategy

    strategy = MbuStrategy()

    def format_reference(n, start_date):
        if n.queue_name == config.MBU_QUEUE_SUPERVISOR:
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
        queue_name=config.MBU_QUEUE_SUPERVISOR,
        handle_item=lambda d: send_mail_to_supervisor(d),
        flow_label="MBU",
        extract_meta=lambda d: (
            "email",
            d.get("email", "n/a"),
            "message_texts/mbu/mbu_supervisor_email_text.html",
        ),
    )

    # Handle employee Digital Post (unified logging)
    process_queue(
        orchestrator_connection,
        queue_name=config.MBU_QUEUE_EMPLOYEE,
        handle_item=lambda d: send_digital_post_to_employee(d["cpr"], d["name"], kombit_access),
        flow_label="MBU",
        extract_meta=lambda d: (
            "digital_post",
            d.get("cpr", "n/a"),
            "message_texts/mbu/mbu_digital_post.html",
        ),
    )
