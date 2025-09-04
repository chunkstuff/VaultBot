import discord
import traceback
from discord.ext import commands
from discord import app_commands, Interaction
from config.settings import settings
from utils.decorators import is_authorised
from core.services.email_service import email_template_autocomplete
from .embed import send_register_embed, send_single_use_register_embed
from .state import registration_state

class RegisterAdmin(commands.GroupCog, name="vaultplus"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def set_embed_config(self, title=None, description=None, image_url=None, footer=None) -> dict:
        # Merge provided values with current embed config
        current = settings.get_embed_config("register_embed")
        return {
            "title": title or current.get("title"),
            "description": description or current.get("description"),
            "image_url": image_url or current.get("image_url"),
            "footer": footer or current.get("footer"),
        }

    @app_commands.command(name="update_register_embed", description="Update the registration embed details.")
    @app_commands.describe(
        title="Embed title",
        description="Embed description",
        image_url="Optional image URL",
        footer="Optional footer text"
    )
    @is_authorised()
    async def update_embed(
        self,
        interaction: Interaction,
        title: str = None,
        description: str = None,
        image_url: str = None,
        footer: str = None
    ):
        try:
            config = self.set_embed_config(title, description, image_url, footer)

            settings.update_embed_config(
                key="register_embed",
                title=config["title"],
                description=config["description"],
                image_url=config["image_url"],
                footer=config["footer"]
            )

            await interaction.response.defer(thinking=True)
            await send_register_embed(self.bot)
            await interaction.followup.send("✅ Embed updated and refreshed.", ephemeral=True)

        except Exception:
            import traceback
            trace = traceback.format_exc()
            await interaction.client.error_reporter.send_admin_alert(trace, context="/vaultplus update_embed")
            await interaction.followup.send("❌ Failed to update embed. Admins have been alerted.", ephemeral=True)


    @app_commands.command(name="open_registration", description="Open registration for Vault+")
    @app_commands.describe(slots="How many users can register")
    @is_authorised()
    async def open_registration(self, interaction: Interaction, slots: int = 0):
        registration_state.reset(max_slots=slots)
        await send_register_embed(self.bot)
        await interaction.response.send_message(f"✅ Registration opened for {slots} users.", ephemeral=True)

    @app_commands.command(name="close_registration", description="Close Vault+ registration")
    @is_authorised()
    async def close_registration(self, interaction: Interaction):
        registration_state.close()
        await send_register_embed(self.bot)
        await interaction.response.send_message("🔒 Registration closed.", ephemeral=True)

    @app_commands.command(name="send_single_register", description="Send a one-time use register embed")
    @is_authorised()
    async def send_single_register(self, interaction: Interaction):
        channel = interaction.channel
        if not isinstance(channel, TextChannel):
            await interaction.response.send_message("❌ You must run this in a text channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await send_single_use_register_embed(channel)
        await interaction.followup.send("📨 Single-use registration embed sent.", ephemeral=True)

    @app_commands.command(name="test_email", description="Send a test Vault+ email.")
    @app_commands.describe(
        email="The recipient's email address",
        template="Choose email type to test"
    )
    @app_commands.autocomplete(template=email_template_autocomplete)
    @is_authorised()
    async def test_email(
        self,
        interaction: Interaction,
        email: str,
        template: str = "registration"
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.bot.registration_notifier.email_service.send_vaultplus_email(
                email=email,
                username="piggyuser",
                password="Vault123!",
                login_url="https://members.thevault.locker",
                template=template
            )
            await interaction.followup.send(f"✅ `{template}` email sent to `{email}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)
            print(traceback.format_exc())

async def setup(bot):
    await bot.add_cog(RegisterAdmin(bot))
