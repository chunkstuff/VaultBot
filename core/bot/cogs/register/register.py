import traceback
from discord import app_commands, Interaction, Embed
from discord.ext import commands
from core.bot.bot import VaultBot
from config.settings import settings
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class RegisterCog(commands.Cog):
    def __init__(self, bot: VaultBot):
        self.bot = bot

    @app_commands.command(name="register", description="Register a new The Vault+ account.")
    async def register(self, interaction: Interaction):
        discord_user = interaction.user
        discord_user_id = str(discord_user.id)
        discord_username = str(discord_user)
        jellyfin_username = discord_user.name  # or .display_name for nicknames
        profile_picture_url = discord_user.display_avatar.url if discord_user.display_avatar else None

        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            response = await self.bot.register_vault_plus_user(
                    interaction=interaction,
                    discord_user_id=discord_user_id,
                    discord_username=discord_username,
                    jellyfin_username=jellyfin_username,
                    profile_picture_url=profile_picture_url,
                )

        except Exception:
            trace = traceback.format_exc()
            logger.exception("Unhandled exception in register command")
            await self.bot.admin_notifier.send_admin_alert(trace)
            response = "❌ An unexpected error occurred. Admins have been notified."

        await interaction.followup.send(response, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RegisterCog(bot))
