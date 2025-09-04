from discord.ext import commands
from discord import app_commands, Interaction, TextChannel
from config.settings import settings
from .embed import send_register_embed

class RegisterCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="send_register", description="Send or update the Vault+ registration embed.")
    async def send_register(self, interaction: Interaction):
        default_channel = interaction.guild.get_channel(settings.REGISTER_DEFAULT_CHANNEL_ID)

        if not isinstance(default_channel, TextChannel):
            await interaction.response.send_message("❌ Default channel is not available or valid.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        await send_register_embed(self.bot)
        await interaction.followup.send("✅ Registration embed sent or updated.", ephemeral=True)
