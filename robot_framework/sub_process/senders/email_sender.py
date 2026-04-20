"""Email sender utility used by flows to send HTML emails based on templates.

This module is intentionally thin and keeps behavior identical to the current
implementation by:
- Reading HTML templates from disk (same file paths as before)
- Performing simple {{Var}} replacement using a provided context dict
- Delegating the actual send to itk_dev_shared_components.smtp.smtp_util
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from itk_dev_shared_components.smtp import smtp_util


@dataclass(frozen=True)
class EmailConfig:
    smtp_server: str
    smtp_port: int


class EmailSender:
    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    @staticmethod
    def _render_template(template_path: str, context: Mapping[str, str]) -> str:
        with open(template_path, encoding="utf-8") as f:
            content = f.read()
        # naive placeholder replacement: {{Key}} -> value
        for key, value in context.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))
        return content

    def send_from_template(
        self,
        *,
        template_path: str,
        context: Mapping[str, str],
        receiver: str,
        sender: str,
        subject: str,
        attachments: list | None = None,
    ) -> None:
        html = self._render_template(template_path, context)
        smtp_util.send_email(
            receiver=receiver,
            sender=sender,
            subject=subject,
            body=html,
            html_body=True,
            attachments=attachments,
            smtp_port=self._config.smtp_port,
            smtp_server=self._config.smtp_server,
        )
