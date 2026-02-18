import base64
from io import BytesIO

import pyodbc
from python_serviceplatformen.models.message import create_digital_post_with_main_document, Sender, Recipient, File
from python_serviceplatformen import digital_post
from itk_dev_shared_components.smtp import smtp_util
from python_serviceplatformen.authentication import KombitAccess

from robot_framework import config

MBU_MAIL_SENDER = "senioradvis@mbu.aarhus.dk"


def get_people():
    connection = pyodbc.connect("Server=FaellesSQL;Database=Personale;Trusted_Connection=yes;Driver={ODBC Driver 17 for SQL Server}")
    cursor = connection.cursor()


def send_mail_to_supervisor(receiver: str, supervisor_name: str, worker_names: list[str]):
    with open("message_texts/mbu_supervisor_email_text.txt", encoding="utf-8") as file:
        mail_text = file.read()

    mail_text = (
        mail_text
        .replace("{{LederNavn}}", supervisor_name)
        .replace("{{MedarbejderNavn}}", "\n".join(worker_names))
    )

    with open("message_texts/MBU Supervisor letter.pdf", "rb") as pdf_file:
        pdf_bytes = BytesIO(pdf_file.read())

    attachment = smtp_util.EmailAttachment(file=pdf_bytes, file_name="Følgebrev.pdf")  # TODO

    smtp_util.send_email(
        receiver=receiver,
        sender=MBU_MAIL_SENDER,
        subject="Din medarbejder skal indkaldes til seniorsamtale",
        body=mail_text,
        attachments=[attachment],
        smtp_port=config.SMTP_PORT,
        smtp_server=config.SMTP_SERVER
    )


def send_digital_post_to_worker(cpr: str, name: str, age: str, kombit_access: KombitAccess):
    with open("message_texts/mbu_digital_post.html", encoding="utf-8") as file:
        letter_text = file.read()

    letter_text = (
        letter_text
        .replace("{{Navn}}", name)
        .replace("{{År}}", age)
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
