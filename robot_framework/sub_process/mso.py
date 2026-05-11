"""This module contains the process for MSO."""

import base64
import calendar
from datetime import date
import json

import pyodbc
from python_serviceplatformen.models.message import create_digital_post_with_main_document, Sender, Recipient, File
from python_serviceplatformen import digital_post
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.smtp import smtp_util
from itk_dev_shared_components.misc import cpr_util
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus

from robot_framework import config
from robot_framework.sub_process.models import Supervisor, Employee


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
    with open("message_texts/mso/mso_supervisor_email_text.html", encoding="utf-8") as file:
        mail_text = file.read()

    employee_strings = [f"<li>{w}</li>" for w in supervisor["employees"]]

    mail_text = (
        mail_text
        .replace("{{LederNavn}}", supervisor["name"])
        .replace("{{MedarbejderNavne}}", "\n".join(employee_strings))
    )

    smtp_util.send_email(
        receiver=supervisor["email"],
        sender=config.MSO_MAIL_SENDER,
        subject="Din medarbejder skal indkaldes til seniorsamtale",
        body=mail_text,
        html_body=True,
        smtp_port=config.SMTP_PORT,
        smtp_server=config.SMTP_SERVER
    )


def send_digital_post_to_employee(cpr: str, name: str, kombit_access: KombitAccess):
    """Send Digital Post to the given employee.

    Args:
        cpr: Cpr of the employee.
        name: Name of the employee
        kombit_access: KombitAccess object used for authentication.
    """
    with open("message_texts/mso/mso_employee_digital_post_text.html", encoding="utf-8") as file:
        letter_text = file.read()

    letter_text = (
        letter_text
        .replace("{{Navn}}", name)
        .replace("{{År}}", str(cpr_util.get_age(cpr)))
    )

    message = create_digital_post_with_main_document(
        label="Tilbud om seniorsamtale",
        sender=Sender(
            senderID="55133018",
            idType="CVR",
            label="Aarhus Kommune"
        ),
        recipient=Recipient(
            recipientID=cpr,
            idType="CPR"
        ),
        files=[
            File(
                encodingFormat="text/html",
                filename="Besked.html",
                language="da",
                content=base64.b64encode(letter_text.encode()).decode()
            )
        ]
    )

    digital_post.send_message(message_type="Digital Post", message=message, kombit_access=kombit_access)


def append_queue(orchestrator_connection: OrchestratorConnection):
    """Search for employees and supervisors who should be notified and
    and them to the job queue.
    """
    start_date, end_date = get_period()
    supervisors = get_people(start_date, end_date)

    for supervisor in supervisors:
        supervisor_reference = f"{supervisor.email} - {start_date.strftime('%d/%m/%Y')}"

        if not orchestrator_connection.get_queue_elements(config.MSO_QUEUE_SUPERVISOR, reference=supervisor_reference):
            orchestrator_connection.create_queue_element(
                queue_name=config.MSO_QUEUE_SUPERVISOR,
                reference=supervisor_reference,
                data=json.dumps(supervisor.to_dict(), ensure_ascii=False)
            )

        for employee in supervisor.employees:
            if not orchestrator_connection.get_queue_elements(config.MSO_QUEUE_EMPLOYEE, reference=employee.cpr):
                orchestrator_connection.create_queue_element(
                    queue_name=config.MSO_QUEUE_EMPLOYEE,
                    reference=employee.cpr,
                    data=json.dumps(employee.to_dict(), ensure_ascii=False)
                )


def handle_queue(orchestrator_connection: OrchestratorConnection, kombit_access: KombitAccess):
    """Handle any queue elements in the two orchestrator queues.

    Args:
        orchestrator_connection: The connection to orchestrator.
        kombit_access: KombitAccess object used for authentication.
    """
    # Handle supervisor emails
    while queue_element := orchestrator_connection.get_next_queue_element(config.MSO_QUEUE_SUPERVISOR):
        try:
            data = json.loads(queue_element.data)
            orchestrator_connection.log_info(f"MSO: Sending mail to {data['email']}")
            send_mail_to_supervisor(data)
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.DONE)
        except Exception:
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.FAILED)
            raise

    # Handle employee Digital Post
    while queue_element := orchestrator_connection.get_next_queue_element(config.MSO_QUEUE_EMPLOYEE):
        try:
            data = json.loads(queue_element.data)
            orchestrator_connection.log_info(f"MSO: Sending Digital Post to {data['cpr']}")
            send_digital_post_to_employee(data["cpr"], data["name"], kombit_access)
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.DONE)
        except Exception:
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.FAILED)
            raise
