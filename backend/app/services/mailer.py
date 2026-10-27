"""사내 SMTP 메일 발송 (TRD §7.6). 외부 SaaS 메일 API 를 쓰지 않는다. 본문·수신자는 로그에 남기지 않는다 (NFR-S1)."""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


class MailNotConfigured(Exception):
    """SMTP_HOST 미설정."""


class MailSendFailed(Exception):
    """SMTP 연결·전송 실패."""


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings):
        self.s = settings

    def _send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=10) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        if not self.s.smtp_host:
            raise MailNotConfigured
        try:
            await asyncio.to_thread(self._send, to, subject, body)
        except (OSError, smtplib.SMTPException) as e:
            raise MailSendFailed(type(e).__name__) from e
