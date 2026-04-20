"""This module contains the process for MBA."""

import calendar
from datetime import date
import json

import pyodbc

from itk_dev_shared_components.misc import cpr_util
from itk_dev_shared_components.smtp import smtp_util
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus

from robot_framework import config
from robot_framework.sub_process.models import Supervisor, Employee


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
    with open("message_texts/mba/mail_supervisor_under_63.html", encoding="utf-8") as file:
        mail_text_under_63 = file.read()

    with open("message_texts/mba/mail_supervisor_over_63.html", encoding="utf-8") as file:
        mail_text_over_63 = file.read()

    for employee in supervisor["employees"]:
        if employee["age"] < 63:
            mail_text = mail_text_under_63
        else:
            mail_text = mail_text_over_63

        mail_text = (
            mail_text
            .replace("{{LederNavn}}", supervisor["name"])
            .replace("{{MedarbejderNavn}}", employee["name"])
        )

        smtp_util.send_email(
            receiver=supervisor["email"],
            sender=config.MBA_MAIL_SENDER,
            subject="Din medarbejder skal indkaldes til seniorsamtale",
            body=mail_text,
            html_body=True,
            smtp_port=config.SMTP_PORT,
            smtp_server=config.SMTP_SERVER
        )


def send_mails_to_employee(employee: dict):
    """Send an email to the given employee.

    Args:
        supervisor: A dictionary as made by Employee.to_dict.
    """
    if cpr_util.get_age(employee["cpr"]) < 63:
        with open("message_texts/mba/mail_employee_under_63.html", encoding="utf-8") as file:
            mail_text = file.read()
    else:
        with open("message_texts/mba/mail_employee_over_63.html", encoding="utf-8") as file:
            mail_text = file.read()

    mail_text = (
        mail_text
        .replace("{{Navn}}", employee["name"])
    )

    smtp_util.send_email(
        receiver=employee["email"],
        sender=config.MBA_MAIL_SENDER,
        subject="Tilbud om seniorsamtale",
        body=mail_text,
        html_body=True,
        smtp_port=config.SMTP_PORT,
        smtp_server=config.SMTP_SERVER
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

    strategy = MbaStrategy()

    for start_date, end_date in strategy.select_periods():
        supervisors = strategy.find_people(start_date, end_date)
        notifications = strategy.plan_notifications(supervisors)

        for n in notifications:
            payload = json.dumps(strategy.serialize(n), ensure_ascii=False)
            queue_name = n.queue_name

            # Preserve historical reference format for supervisors: "<email> - <dd/mm/YYYY>"
            if queue_name == config.MBA_QUEUE_SUPERVISOR:
                # n.recipient.address is supervisor email
                reference = f"{n.recipient.address} - {start_date.strftime('%d/%m/%Y')}"
            else:
                # Employees keep CPR as reference
                reference = n.reference

            if not orchestrator_connection.get_queue_elements(queue_name, reference=reference):
                orchestrator_connection.create_queue_element(
                    queue_name=queue_name,
                    reference=reference,
                    data=payload,
                )


def handle_queue(orchestrator_connection: OrchestratorConnection):
    """Handle any queue elements in the two orchestrator queues.

    Args:
        orchestrator_connection: The connection to orchestrator.
    """
    # Handle supervisor emails
    while queue_element := orchestrator_connection.get_next_queue_element(config.MBA_QUEUE_SUPERVISOR):
        try:
            data = json.loads(queue_element.data)
            orchestrator_connection.log_info(f"MBA: Sending mail to {data['email']}")
            send_mails_to_supervisor(data)
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.DONE)
        except Exception:
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.FAILED)
            raise

    # Handle employee Mails
    while queue_element := orchestrator_connection.get_next_queue_element(config.MBA_QUEUE_EMPLOYEE):
        try:
            data = json.loads(queue_element.data)
            orchestrator_connection.log_info(f"MBA: Sending mail to {data['email']}")
            send_mails_to_employee(data)
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.DONE)
        except Exception:
            orchestrator_connection.set_queue_element_status(queue_element.id, status=QueueStatus.FAILED)
            raise
