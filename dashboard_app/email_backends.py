"""
Brevo (HTTPS API) email backend.

Kyun: Render ke free plan par SMTP ports (25/465/587) block/unreliable hote hain
("OSError: [Errno 101] Network is unreachable"). Ye backend email HTTPS (port 443) se bhejta hai,
jo block nahi hota. Koi extra library nahi chahiye (sirf Python ka urllib).

Use karne ke liye Render > Environment mein:
    EMAIL_BACKEND = dashboard_app.email_backends.BrevoAPIEmailBackend
    BREVO_API_KEY = <Brevo ki API key>      (secret - kisi ko mat dikhana, git mein mat daalna)
    EMAIL_HOST_USER = <Brevo mein verified sender email>   (from-address yahi use hota hai)
"""
import base64
import json
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoAPIError(Exception):
    pass


def _addr(value):
    name, email = parseaddr(value)
    d = {"email": email}
    if name:
        d["name"] = name
    return d


class BrevoAPIEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "BREVO_API_KEY", "") or ""
        self.timeout = getattr(settings, "EMAIL_TIMEOUT", None) or 10

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages or []:
            try:
                self._send(message)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent

    def _build_payload(self, m):
        sender = _addr(m.from_email or settings.DEFAULT_FROM_EMAIL)
        if not sender.get("name"):
            sender["name"] = "Tejas Modi Portfolio"
        payload = {
            "sender": sender,
            "to": [_addr(a) for a in m.to],
            "subject": m.subject,
        }
        if m.content_subtype == "html":
            payload["htmlContent"] = m.body
        else:
            payload["textContent"] = m.body
        if m.cc:
            payload["cc"] = [_addr(a) for a in m.cc]
        if m.bcc:
            payload["bcc"] = [_addr(a) for a in m.bcc]
        if m.reply_to:
            payload["replyTo"] = _addr(m.reply_to[0])

        attachments = []
        for att in m.attachments:
            if isinstance(att, (tuple, list)):
                filename, content, _mimetype = att
                if isinstance(content, str):
                    content = content.encode("utf-8")
            else:  # MIMEBase object
                filename = att.get_filename() or "attachment"
                content = att.get_payload(decode=True) or b""
            attachments.append({"name": filename, "content": base64.b64encode(content).decode("ascii")})
        if attachments:
            payload["attachment"] = attachments
        return payload

    def _send(self, m):
        if not self.api_key:
            raise BrevoAPIError("BREVO_API_KEY is not set")
        if not m.recipients():
            return
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(self._build_payload(m)).encode("utf-8"),
            headers={"api-key": self.api_key, "accept": "application/json", "content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            # Sirf status + Brevo ka error text (isme API key nahi hoti)
            detail = exc.read().decode("utf-8", "replace")[:150] if hasattr(exc, "read") else ""
            raise BrevoAPIError(f"Brevo API HTTP {exc.code}: {detail}") from None
