"""This module contains configuration constants used across the framework"""

# The number of times the robot retries on an error before terminating.
MAX_RETRY_COUNT = 3

# Whether the robot should be marked as failed if MAX_RETRY_COUNT is reached.
FAIL_ROBOT_ON_TOO_MANY_ERRORS = True

# Error screenshot config
SMTP_SERVER = "smtp.adm.aarhuskommune.dk"
SMTP_PORT = 25
SCREENSHOT_SENDER = "robot@friend.dk"

# Constant/Credential names
ERROR_EMAIL = "Error Email"
KEYVAULT_CREDENTIALS = "Keyvault"
KEYVAULT_URI = "Keyvault URI"

# Local constants
KEYVAULT_PATH = "Digital_Post_Senioradvis"  # TODO
MBU_MAIL_SENDER = "senioradvis@mbu.aarhus.dk"
MSO_MAIL_SENDER = "senioradvis@mso.aarhus.dk"
MBA_MAIL_SENDER = "senioradvis@ba.aarhus.dk"

# Queues
MBU_QUEUE_EMPLOYEE = "MBU_Senioradvisering_medarbejder"
MBU_QUEUE_SUPERVISOR = "MBU_Senioradvisering_leder"

MSO_QUEUE_EMPLOYEE = "MSO_Senioradvisering_medarbejder"
MSO_QUEUE_SUPERVISOR = "MSO_Senioradvisering_leder"

MBA_QUEUE_EMPLOYEE = "MBA_Senioradvisering_medarbejder"
MBA_QUEUE_SUPERVISOR = "MBA_Senioradvisering_leder"
