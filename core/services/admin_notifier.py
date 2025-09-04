import traceback
import discord
from config.settings import settings
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class AdminNotifier:
    def __init__(self, bot: discord.Client | None = None):
        self.bot = bot

    async def send_admin_alert(self, error: Exception | str, context: str = "Unhandled"):
        channel = self.bot.get_channel(settings.ADMIN_CHANNEL)
        if not channel:
            logger.warning("ADMIN_CHANNEL not found.")
            return

        trace = error if isinstance(error, str) else traceback.format_exc()

        embed = discord.Embed(
            title="🚨 Admin Alert",
            description=f"**Context:** {context}",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Traceback",
            value=f"```py\n{trace[:1010]}{'...' if len(trace) > 1010 else ''}```",
            inline=False
        )

        await channel.send(content=f"<@{settings.DEVELOPER_ID}>", embed=embed)
        logger.warning(f"Alert sent to ADMIN_CHANNEL: {context}")

    async def send_registration_notice(self, discord_user: discord.User, jellyfin_username: str, email: str):
        channel = self.bot.get_channel(settings.ADMIN_CHANNEL)
        if not channel:
            logger.warning("ADMIN_CHANNEL not found.")
            return

        embed = discord.Embed(
            title="✅ New Vault+ Registration",
            color=discord.Color.green()
        )
        embed.add_field(name="Discord User", value=f"{discord_user} ({discord_user.id})", inline=False)
        embed.add_field(name="Jellyfin Username", value=jellyfin_username, inline=True)
        embed.add_field(name="Email", value=email, inline=True)

        await channel.send(embed=embed)
        logger.info(f"✅ Sent registration notice for {jellyfin_username}.")

    async def send_generic_notice(self, title: str, message: str, *, context: str = None, color: discord.Color = discord.Color.blue()):
        channel = self.bot.get_channel(settings.ADMIN_CHANNEL)
        if not channel:
            logger.warning("ADMIN_CHANNEL not found.")
            return

        embed = discord.Embed(title=title, description=message, color=color)
        if context:
            embed.set_footer(text=f"Context: {context}")

        await channel.send(embed=embed)
