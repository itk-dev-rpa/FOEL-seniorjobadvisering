import base64

import pyodbc
from python_serviceplatformen.models.message import create_digital_post_with_main_document, Sender, Recipient, File
from python_serviceplatformen import digital_post
from itk_dev_shared_components.smtp import smtp_util
from python_serviceplatformen.authentication import KombitAccess

from robot_framework import config

MBU_MAIL_SENDER = "senioradvis@mso.aarhus.dk"


def get_people():
    connection = pyodbc.connect("Server=FaellesSQL;Database=Personale;Trusted_Connection=yes;Driver={ODBC Driver 17 for SQL Server}")
    cursor = connection.cursor()


def send_mail_to_supervisor(receiver: str, supervisor_name: str, worker_names: list[str], age: str):
    with open("message_texts/mso_supervisor_email_text.html", encoding="utf-8") as file:
        mail_text = file.read()

    worker_names_text = ""
    for name in worker_names:
        worker_names_text += f"<li>{name}</li>\n"

    mail_text = (
        mail_text
        .replace("{{LederNavn}}", supervisor_name)
        .replace("{{MedarbejderNavn}}", worker_names_text)
        .replace("{{År}}", age)
    )

    smtp_util.send_email(
        receiver=receiver,
        sender=MBU_MAIL_SENDER,
        subject="Din medarbejder skal indkaldes til seniorsamtale",
        body=mail_text,
        html_body=True,
        smtp_port=config.SMTP_PORT,
        smtp_server=config.SMTP_SERVER
    )


def send_mail_to_worker(receiver: str, name: str, age: str):
    with open("message_texts/mso_worker_email_text.html", encoding="utf-8") as file:
        mail_text = file.read()

    mail_text = (
        mail_text
        .replace("{{Navn}}", name)
        .replace("{{År}}", age)
    )

    smtp_util.send_email(
        receiver=receiver,
        sender=MBU_MAIL_SENDER,
        subject="Din medarbejder skal indkaldes til seniorsamtale",
        body=mail_text,
        html_body=True,
        smtp_port=config.SMTP_PORT,
        smtp_server=config.SMTP_SERVER
    )