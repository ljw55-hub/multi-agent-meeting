from __future__ import annotations

import asyncio
import logging
import os
from email.message import EmailMessage

import aiosmtplib
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class EmailClient:
    """SMTP client for sending meeting reports."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_addr: str | None = None,
    ) -> None:
        self.host = host or os.getenv("SMTP_HOST", "")
        self.port = port or int(os.getenv("SMTP_PORT", "587"))
        self.username = username or os.getenv("SMTP_USER", "")
        self.password = password or os.getenv("SMTP_PASSWORD", "")
        self.from_addr = from_addr or os.getenv("SMTP_FROM", self.username)

    @property
    def is_enabled(self) -> bool:
        return bool(self.host and self.from_addr)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def send_email(self, to: list[str], subject: str, body: str, html: str | None = None) -> bool:
        if not self.is_enabled or not to:
            return False

        message = EmailMessage()
        message["From"] = self.from_addr
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")

        try:
            start_tls = self.port == 587
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username or None,
                password=self.password or None,
                start_tls=start_tls,
                use_tls=(self.port == 465),
                timeout=30,
            )
            logger.info("Meeting email sent to %s", to)
            return True
        except (aiosmtplib.SMTPException, OSError, asyncio.TimeoutError) as exc:
            logger.warning("SMTP send failed: %s", exc)
            return False

    async def send_meeting_report(
        self,
        title: str,
        recipients: list[str],
        summary_md: str,
        actions_md: str,
        insights_md: str,
    ) -> bool:
        body = (
            f"Meeting: {title}\n\n"
            f"Summary\n{summary_md}\n\n"
            f"Action Items\n{actions_md}\n\n"
            f"Insights\n{insights_md}\n"
        )
        return await self.send_email(recipients, f"Meeting Report | {title}", body)
