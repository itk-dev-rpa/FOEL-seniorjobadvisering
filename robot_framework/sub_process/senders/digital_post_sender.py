"""Digital Post sender utility used by flows to send main documents via Serviceplatformen.

Scope in this step:
- Provide a thin wrapper around python_serviceplatformen to keep flows clean.
- No wiring yet in MBU/MSO; flows will adopt this in a later commit.
- Keep behavior configurable by passing Sender/KombitAccess explicitly.

Notes:
- We reuse the same naive {{Var}} replacement as EmailSender to keep parity
  with existing template handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import base64

from python_serviceplatformen.models.message import (
    create_digital_post_with_main_document,
    Sender,
    Recipient,
    File,
)
from python_serviceplatformen import digital_post
from python_serviceplatformen.authentication import KombitAccess


@dataclass(frozen=True)
class DigitalPostConfig:
    main_doc_name: str = "main.html"
    main_doc_mime: str = "text/html"


class DigitalPostSender:
    def __init__(self, config: DigitalPostConfig | None = None) -> None:
        self._config = config or DigitalPostConfig()

    @staticmethod
    def _render_template(template_path: str, context: Mapping[str, str]) -> str:
        with open(template_path, encoding="utf-8") as f:
            content = f.read()
        for key, value in context.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))
        return content

    def build_message_from_template(
        self,
        *,
        template_path: str,
        context: Mapping[str, str],
        recipient_cpr: str,
        sender: Sender,
        subject: str,
    ):
        html = self._render_template(template_path, context)
        html_bytes = html.encode("utf-8")
        main_file = File(
            name=self._config.main_doc_name,
            data=base64.b64encode(html_bytes).decode("ascii"),
            mime_type=self._config.main_doc_mime,
        )
        recipient = Recipient(cpr=recipient_cpr)
        message = create_digital_post_with_main_document(
            sender=sender,
            recipient=recipient,
            main_document=main_file,
            subject=subject,
        )
        return message

    def send_from_template(
        self,
        *,
        template_path: str,
        context: Mapping[str, str],
        recipient_cpr: str,
        sender: Sender,
        subject: str,
        kombit_access: KombitAccess,
    ) -> None:
        message = self.build_message_from_template(
            template_path=template_path,
            context=context,
            recipient_cpr=recipient_cpr,
            sender=sender,
            subject=subject,
        )
        digital_post.send(kombit_access, message)
