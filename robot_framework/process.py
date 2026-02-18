"""This module contains the main process of the robot."""

import os

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess

from robot_framework.sub_process import mbu, mso


# pylint: disable-next=unused-argument
def process(orchestrator_connection: OrchestratorConnection) -> None:
    """Do the primary process of the robot."""
    orchestrator_connection.log_trace("Running process.")

    certificate_path = r"C:\Repos\GHBM\OpenPostbud\.certs\Certificate.pem"  # TODO
    kombit_access = KombitAccess("55133018", certificate_path, test=True)  # TODO

    mbu.send_mail_to_supervisor("ghbm@aarhus.dk", "Mathias", ["Sebastian","Sebastian","Sebastian",])
    # mbu.send_digital_post_to_worker("2611740000", "Hans", "5019", kombit_access)

    # mso.send_mail_to_worker("ghbm@aarhus.dk", "Mathias", "76")
    # mso.send_mail_to_supervisor("ghbm@aarhus.dk", "Mathias", ["Mads","Mads","Mads",], "134")


if __name__ == '__main__':
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Senioradvisering test", conn_string, crypto_key, "", "")
    process(oc)
