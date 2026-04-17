"""This module contains the main process of the robot."""

import json
import os

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from hvac import Client

from robot_framework import config
from robot_framework.sub_process import mbu, mso, mba


# pylint: disable-next=unused-argument
def process(orchestrator_connection: OrchestratorConnection) -> None:
    """Do the primary process of the robot."""
    orchestrator_connection.log_trace("Running process.")

    kombit_access = get_kombit_access(orchestrator_connection)

    departments = json.loads(orchestrator_connection.process_arguments)["departments"]

    if "mbu" in departments:
        mbu.append_queue(orchestrator_connection)

    if "mso" in departments:
        mso.append_queue(orchestrator_connection)

    if "mba" in departments:
        mba.append_queue(orchestrator_connection)

    mbu.handle_queue(orchestrator_connection, kombit_access)
    mso.handle_queue(orchestrator_connection, kombit_access)
    mba.handle_queue(orchestrator_connection)


def get_kombit_access(orchestrator_connection: OrchestratorConnection) -> KombitAccess:
    """Get the Kombit certificate from the vault and create a KombitAccess object."""
    vault_auth = orchestrator_connection.get_credential(config.KEYVAULT_CREDENTIALS)
    vault_uri = orchestrator_connection.get_constant(config.KEYVAULT_URI).value

    vault_client = Client(vault_uri)
    vault_client.auth.approle.login(role_id=vault_auth.username, secret_id=vault_auth.password)

    # Get certificate
    read_response = vault_client.secrets.kv.v2.read_secret_version(mount_point='rpa', path=config.KEYVAULT_PATH, raise_on_deleted_version=True)
    certificate = read_response['data']['data']['cert']

    # Because KombitAccess requires a file, we save and delete the certificate after we use it
    certificate_path = "certificate.pem"
    with open(certificate_path, 'w', encoding='utf-8') as cert_file:
        cert_file.write(certificate)

    # Prepare access to service platform
    return KombitAccess("55133018", certificate_path)



if __name__ == '__main__':
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Senioradvisering test", conn_string, crypto_key, '{"departments": ["mbu", "mso", "mba"]}', "")
    process(oc)
