# core/bot/cogs/login/cog.py

import discord
from discord.ext import commands
from discord import app_commands, Interaction

from config.settings import settings
from utils.decorators import is_authorised
from .embed import send_login_embed

class LoginAdmin(commands.GroupCog, name="loginadmin"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="refresh_login_embed", description="Re-send or update the login embed.")
    @is_authorised()
    async def refresh_login_embed(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)
        await send_login_embed(self.bot)
        await interaction.followup.send("✅ Login embed updated.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(LoginAdmin(bot))
