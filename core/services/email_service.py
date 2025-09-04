from email.message import EmailMessage
from pathlib import Path
import aiosmtplib
from config.settings import settings
from discord import app_commands
from typing import List

TEMPLATE_DIR = Path("config/email_templates")

SUBJECTS = {
    "registration": "Vault+ Access Granted",
    "purchase": "Welcome to The Vault, piggy",
}

TEMPLATE_CHOICES = list(SUBJECTS.keys())

class EmailService:
    def __init__(self):
        self.smtp_host = settings.SMTP_SERVER
        self.smtp_port = settings.SMTP_PORT
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.from_address = settings.EMAIL_FROM

    def render_templates(self, username: str, password: str, login_url: str, template: str = "registration"):
        html_path = TEMPLATE_DIR / f"{template}.html"
        txt_path = TEMPLATE_DIR / f"{template}.txt"

        html = html_path.read_text().format(username=username, password=password, login_url=login_url)
        text = txt_path.read_text().format(username=username, password=password, login_url=login_url)
        return text, html

    async def send_vaultplus_email(
        self,
        email: str,
        username: str,
        password: str,
        login_url: str,
        template: str = "registration"
    ):
        text, html = self.render_templates(username, password, login_url, template)

        subject = SUBJECTS.get(template, "Vault+ Notification")

        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = email
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=self.smtp_host,
            port=self.smtp_port,
            use_tls=True,
            username=self.username,
            password=self.password,
        )

async def email_template_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=choice, value=choice)
        for choice in TEMPLATE_CHOICES
        if current.lower() in choice.lower()
    ]
