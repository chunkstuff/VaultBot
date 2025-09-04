import traceback
import discord
from utils.validation import is_valid_email, is_valid_username, generate_password
from config.settings import settings
from core.bot.cogs.register.state import registration_state
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class RegisterModal(discord.ui.Modal, title="Vault+ Registration"):
    username = discord.ui.TextInput(
        label="Desired Username",
        placeholder="alphanumeric, _ or . (3–32 chars)",
        min_length=3,
        max_length=32,
        required=True
    )

    email = discord.ui.TextInput(
        label="Email Address",
        placeholder="you@example.com",
        required=True
    )

    @staticmethod
    def is_successful_registration(result: str) -> bool:
        return result.startswith("## ✅")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if registration_state.is_full():
                await interaction.followup.send("😱 Looks like you just missed it, piggy! Registration has now filled up!", ephemeral=True)
                return

            uname = self.username.value.strip()
            email = self.email.value.strip()

            if not is_valid_email(email):
                await interaction.response.send_message("❌ Invalid email format.", ephemeral=True)
                return

            if not is_valid_username(uname):
                await interaction.response.send_message(
                    "❌ Username must be 3–32 characters, alphanumeric + `_` or `.` only.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            user_notifier = interaction.client.registration_notifier.for_user(interaction.user, email=email)
            await user_notifier.start_dm_setup()
           
            # 🔧 Perform registration
            password = generate_password()
            result = await interaction.client.register_vault_plus_user(
                interaction=interaction,
                discord_user_id=str(interaction.user.id),
                discord_username=str(interaction.user),
                jellyfin_username=uname,
                profile_picture_url=interaction.user.display_avatar.url,
                email=email,
                password=password
            )
            
            success = self.is_successful_registration(result)
            
            # ✅ Update DM and send credentials
            await user_notifier.send_credentials(username=uname, password=password, result=result, success=success)        
            await interaction.followup.send("📬 Registration complete! Check your DMs. You should also receive an e-mail shortly if your registration was accepted.", ephemeral=True)

        except Exception:
            trace = traceback.format_exc()
            logger.exception("Unhandled exception in RegisterModal.on_submit")
            await interaction.client.admin_reporter.send_admin_alert(trace, context="Register Modal Submit")
            await interaction.followup.send("❌ Something went wrong — admins have been alerted.", ephemeral=True)

    
