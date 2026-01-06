"""SMTP email sender for HTML newsletters."""

from __future__ import annotations

import html as html_lib
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

import certifi

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailSendResult:
    """Result of an email send attempt."""
    success: bool
    message_id: str | None = None
    error: str | None = None


class SmtpEmailSender:
    """Send HTML emails via SMTP with optional TLS/SSL."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds

    def send_html(
        self,
        *,
        subject: str,
        html: str,
        from_email: str,
        to_emails: list[str],
        reply_to: str | None = None,
    ) -> EmailSendResult:
        """Send a multipart email with text + HTML."""
        if not self.host:
            return EmailSendResult(success=False, error="SMTP host not configured.")
        if not from_email:
            return EmailSendResult(success=False, error="From email is missing.")
        if not to_emails:
            return EmailSendResult(success=False, error="Recipient list is empty.")
        if not self.username or not self.password:
            return EmailSendResult(success=False, error="SMTP credentials are missing.")

        cleaned_to = [email.strip() for email in to_emails if email and email.strip()]
        if not cleaned_to:
            return EmailSendResult(success=False, error="Recipient list is empty after cleanup.")

        message_id = _make_message_id(from_email)
        msg = EmailMessage()
        msg["Subject"] = subject or "SilverTree Newsletter"
        msg["From"] = from_email
        msg["To"] = ", ".join(cleaned_to)
        msg["Message-ID"] = message_id
        if reply_to:
            msg["Reply-To"] = reply_to

        text_fallback = _html_to_text(html)
        msg.set_content(text_fallback or "Newsletter available in HTML format.")
        msg.add_alternative(html or "", subtype="html")

        try:
            if self.use_ssl:
                context = ssl.create_default_context(cafile=certifi.where())
                with smtplib.SMTP_SSL(
                    self.host,
                    self.port,
                    timeout=self.timeout_seconds,
                    context=context,
                ) as smtp:
                    smtp.login(self.username, self.password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
                    smtp.ehlo()
                    if self.use_tls:
                        smtp.starttls(context=ssl.create_default_context(cafile=certifi.where()))
                        smtp.ehlo()
                    smtp.login(self.username, self.password)
                    smtp.send_message(msg)
            return EmailSendResult(success=True, message_id=message_id)
        except Exception as exc:
            logger.exception("SMTP send failed.")
            return EmailSendResult(success=False, error=str(exc))


def _make_message_id(from_email: str) -> str:
    if "@" in from_email:
        domain = from_email.split("@", 1)[1].strip()
        return make_msgid(domain=domain)
    return make_msgid()


def _html_to_text(html: str) -> str:
    if not html:
        return ""

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</h\d>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n\s+\n", "\n\n", text)
    return text.strip()
