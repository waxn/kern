"""SMTP submission (TLS only)."""

from __future__ import annotations

import smtplib
import ssl

from . import account


class SmtpSender:
    """Sends as the account that was active when it was created."""

    def __init__(self):
        self.cfg = account.cfg()
        self.password = account.password()

    def _context(self):
        ctx = ssl.create_default_context()
        if not self.cfg["TLS_VERIFY"]:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def send(self, envelope_from: str, recipients: list[str], raw: bytes) -> dict:
        """Returns {recipient: (code, msg)} for recipients the server refused
        while accepting others. Raises if nobody accepted it."""
        host, port = self.cfg["SMTP_HOST"], self.cfg["SMTP_PORT"]
        password = self.password
        if self.cfg["SMTP_SECURITY"] == "starttls":
            client = smtplib.SMTP(host, port, timeout=60)
            client.starttls(context=self._context())
        else:
            client = smtplib.SMTP_SSL(host, port, timeout=60, context=self._context())
        try:
            client.login(self.cfg["LOGIN"], password)
            refused = client.sendmail(envelope_from, recipients, raw)
            return {k: (v[0], v[1].decode("utf-8", "replace") if isinstance(v[1], bytes) else str(v[1]))
                    for k, v in (refused or {}).items()}
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:
                pass
