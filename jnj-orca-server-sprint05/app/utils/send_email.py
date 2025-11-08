"""
    Utility function to send emails using SMTP.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config.settings import settings


def send_email(to: str, subject: str, body: str):

    """
    Send an email using SMTP.

    Args:
        to (str): Recipient email address.
        subject (str): Subject of the email.
        body (str): Body content of the email.
    Raises:
        Exception: If there is an error sending the email.
    """

    sender_email = settings.smtp_sender
    app_password = settings.smtp_app_password
    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)

    except smtplib.SMTPAuthenticationError:
        raise

    except smtplib.SMTPConnectError:
        raise

    except smtplib.SMTPRecipientsRefused:
        raise

    except smtplib.SMTPException:
        raise

    except Exception:
        raise
