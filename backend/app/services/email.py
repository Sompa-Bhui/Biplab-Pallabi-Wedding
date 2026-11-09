import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings
from app.models import RSVP


class EmailConfigurationError(RuntimeError):
    pass


def send_rsvp_notification(rsvp: RSVP, settings: Settings) -> None:
    settings.validate_email_configuration()

    message = EmailMessage()
    message["Subject"] = "New Wedding RSVP – Biplab & Pallabi"
    message["From"] = settings.mail_from
    message["To"] = str(settings.rsvp_recipient)
    message.set_content(
        "\n".join(
            (
                "A new RSVP was submitted.",
                "",
                f"Guest name: {rsvp.guest_name}",
                f"Mobile: {rsvp.mobile or 'Not provided'}",
                f"Number of guests: {rsvp.guest_count}",
                f"Attendance: {rsvp.attendance}",
                f"Message: {rsvp.message or 'No message provided'}",
                "",
                f"RSVP ID: {rsvp.id}",
            )
        )
    )

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
