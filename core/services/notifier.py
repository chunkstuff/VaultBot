# core/bot/services/notifier.py

import asyncio
import discord
from utils.logger_factory import setup_logger
from core.services.email_service import EmailService

logger = setup_logger(__name__)


class Notifier:
    def __init__(self, email_service: EmailService | None = None):
        self.email_service = email_service

    def for_user(self, user: discord.User, email: str | None = None) -> "UserNotifier":
        return UserNotifier(user=user, email=email, email_service=self.email_service)


class UserNotifier:
    def __init__(self, user: discord.User, email: str | None = None, email_service: EmailService | None = None):
        self.user = user
        self.email = email
        self.email_service = email_service

        self.dm_message: discord.Message | None = None
        self._stop_event = asyncio.Event()
        self._anim_task: asyncio.Task | None = None

    async def start_dm_setup(self) -> bool:
        try:
            embed = discord.Embed(
                title="Vault+ Setup",
                description="📦 Setting up your Vault+ profile",
                color=discord.Color.blurple()
            )
            self.dm_message = await self.user.send(embed=embed)
            self._anim_task = asyncio.create_task(self._animate_embed())
            return True
        except discord.Forbidden:
            logger.warning(f"❌ Could not DM user {self.user}")
            return False

    async def _animate_embed(self):
        try:
            dots = ["", ".", "..", "..."]
            i = 0
            while not self._stop_event.is_set():
                if self.dm_message:
                    embed = self.dm_message.embeds[0] if self.dm_message.embeds else discord.Embed()
                    embed.description = f"📦 Setting up your Vault+ profile{dots[i % 4]}"
                    try:
                        await self.dm_message.edit(embed=embed)
                    except discord.HTTPException:
                        logger.warning("⚠️ Failed to edit setup DM during animation.")
                i += 1
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("💤 DM animation task cancelled.")

    async def send_credentials(
        self,
        username: str,
        password: str,
        result: str,
        success: bool,
        login_url: str = "https://members.thevault.locker",
        template: str = "registration"
    ):
        self._stop_event.set()
        if self._anim_task:
            self._anim_task.cancel()
            try:
                await self._anim_task
            except asyncio.CancelledError:
                pass

        if self.dm_message:
            try:
                embed = self.dm_message.embeds[0] if self.dm_message.embeds else discord.Embed()
                embed.description = "✅ Setup complete!"
                embed.color = discord.Color.green()
                await self.dm_message.edit(embed=embed)
            except Exception:
                logger.warning("⚠️ Failed to finalize animated setup message.")

        try:
            credentials = discord.Embed(
                title="Vault+ Credentials",
                description=result,
                color=discord.Color.dark_teal(),
            )
            credentials.set_footer(text="⚠️ **Please note that the Vault+ is currently in beta. Full functionality has not yet been implemented, and you may experience bugs.**")
            await self.user.send(embed=credentials)
        except discord.Forbidden:
            logger.warning("❌ Could not DM credentials to user.")

        if self.email and self.email_service and success:
            asyncio.create_task(
                self._send_email(username, password, login_url, template)
            )

    async def _send_email(self, username: str, password: str, login_url: str, template: str):
        try:
            await self.email_service.send_vaultplus_email(
                email=self.email,
                username=username,
                password=password,
                login_url=login_url,
                template=template
            )
            logger.info(f"📧 Sent '{template}' email to {self.email}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to send {template} email to {self.email}: {e}")

    async def cancel(self):
        self._stop_event.set()
        if self._anim_task:
            await self._anim_task
