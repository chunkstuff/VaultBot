import string
import secrets
import traceback
import discord
import asyncio
from discord.ext import commands
from discord import app_commands, Interaction

from core.jellyfin_client import JellyfinClient
from core.bot.cogs.login.embed import send_login_embed
from core.bot.cogs.register.embed import send_register_embed
from core.bot.cogs.register.state import registration_state
from config.settings import settings
from core.services.admin_notifier import AdminNotifier
from core.services.notifier import Notifier
from core.services.user_logger import log_registered_user
from errors.exceptions import (
    DiscordAlreadyLinkedSameUsername,
    DiscordAlreadyLinkedDifferentUsername,
    UsernameExistsUnlinked,
    UsernameTaken
)
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class VaultBot(commands.Bot):
    def __init__(self, client, link_map, admin_notifier=None, registration_notifier=None, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.link_map = link_map
        self.admin_notifier = admin_notifier
        self.registration_notifier = registration_notifier

    async def on_ready(self):
        logger.info(f"🤖 Logged in as {self.user} (ID: {self.user.id})")
        logger.info("Bot is ready and connected to Discord.")
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} app command(s).")
        except Exception as e:
            logger.exception("❌ Failed to sync app commands")
            trace = traceback.format_exc()
            await self.admin_notifier.send_admin_alert(trace, context="bot.on_ready")

        # 🔁 Re-attach to persistent registration embed
        try:
            await self.reattach_register_embed()
            await self.reattach_login_embed()
            await self.reattach_worse_embed()
        except Exception as e:
            trace = traceback.format_exc()
            logger.error("❌ Failed to re-attach to registration embed on ready.")
            await self.admin_notifier.send_admin_alert(trace, context="on_ready embed restore")

    async def reattach_register_embed(self):
        await send_register_embed(self)
        logger.info("🔁 Re-attached and refreshed registration embed.")

    async def reattach_login_embed(self):
        await send_login_embed(self)
        logger.info("🔁 Re-attached and refreshed login embed.")

    async def reattach_worse_embed(self):
        cog = self.get_cog("MakeMeWorsePlus")
        if cog:
            await cog.send_worse_embed()
            logger.info("🔁 Re-attached and refreshed worse embed.")

    async def on_member_remove(self, member: discord.Member):
        """
        Handle when a member leaves the guild.
        Disables their Jellyfin account to prevent access after leaving.
        """
        try:
            logger.info(f"🚪 Member left guild: {member.name} ({member.id})")
            
            # Get the Jellyfin user ID from link_map
            jellyfin_id = await self.link_map.get_jellyfin_user_id(str(member.id))
            
            if not jellyfin_id:
                logger.debug(f"No Jellyfin account found for {member.name}")
                return
            
            # Check if the Jellyfin account is already disabled
            user_data = await self.client.api.get_by_jellyfin_user_id(jellyfin_id)
            is_disabled = user_data.get('Policy', {}).get('IsDisabled', False)
            
            if is_disabled:
                logger.debug(f"Jellyfin account for {member.name} already disabled")
                return
            
            # Disable the Jellyfin account using the existing disable method
            await self.client.users.disable_vaultplus_user(jellyfin_id)
            
            logger.info(
                f"✅ Disabled Jellyfin account for {member.name} "
                f"(Jellyfin ID: {jellyfin_id}) - user left guild"
            )
            
            if self.admin_notifier:
                embed = discord.Embed(
                    title="🚪 Member Left - Jellyfin Disabled",
                    description=(
                        f"**User:** {member.mention} ({member.name})\n"
                        f"**Jellyfin ID:** `{jellyfin_id}`\n"
                        f"**Left at:** <t:{int(discord.utils.utcnow().timestamp())}:F>"
                    ),
                    color=discord.Color.orange()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                
                admin_channel = self.get_channel(settings.ADMIN_CHANNEL)
                if admin_channel:
                    await admin_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"❌ Error handling member removal for {member.name} ({member.id}): {e}")
            logger.exception(e)
            
            # Alert admins of the error
            if self.admin_notifier:
                await self.admin_notifier.send_admin_alert(
                    e, 
                    context=f"on_member_remove for {member.name}"
                )

    async def apply_vaultplus_role(self, discord_user_id: int, discord_username: str):
        # Assign Vault+ role
        try:
            guild = discord.utils.get(self.guilds, id=settings.GUILD_ID)
            member = guild.get_member(int(discord_user_id))
            role = discord.utils.get(guild.roles, id=settings.VAULTPLUS_ROLE)
            if guild and member and role:
                await member.add_roles(role, reason="Registered for Vault+")
                logger.info(f"✅ Added Vault+ role to {discord_username}")
            else:
                logger.warning(f"⚠️ Failed to assign Vault+ role to {discord_username} (missing guild/member/role)")
        except Exception as e:
            trace = traceback.format_exc()
            logger.exception(f"❌ Error assigning Vault+ role to {discord_username}: {e}")
            await self.admin_notifier.send_admin_alert(trace, context="bot.apply_vaultplus_role")

    async def disable_subscriber_downloads(self, interaction: discord.Interaction):
        try:
            discord_id = str(interaction.user.id)
            jellyfin_id = await self.client.users.get_jellyfin_user_id(discord_id)
            logger.info(f'DiscordID: {discord_id}; JellyfinID: {jellyfin_id}')
            if jellyfin_id:
                await asyncio.sleep(0.5)
                await self.client.users.api.disable_downloads(jellyfin_id)
                logger.info(f"Downloads disabled for Jellyfin user {jellyfin_id} (Discord: {interaction.user})")
        except Exception as e:
            trace = traceback.format_exc()
            logger.exception(f"❌ Error assigning disabling downloads for {interaction.user}: {e}")
            await self.admin_notifier.send_admin_alert(trace, context="bot.disable_subscriber_downloads")

    async def register_vault_plus_user(
        self,
        interaction: discord.Interaction,
        discord_user_id: str,
        discord_username: str,
        jellyfin_username: str,
        profile_picture_url: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> str:        
        lock = self.client.users.user_locks[discord_user_id]
        if lock.locked():
            logger.info(f"Discord user {discord_username} ({discord_user_id}) already registering as Vault+ user '{jellyfin_username}'")
            return "⏳ Registration is already in progress for your account. Please wait..."

        if not registration_state.can_register():
            logger.info(f"Discord user {discord_username} ({discord_user_id}) could not register as Vault+ user '{jellyfin_username}'; registration now full.")
            return "❌ Registration is currently closed or full."

        async with lock:
            logger.info(f"Registering Discord user {discord_username} ({discord_user_id}) as Vault+ user '{jellyfin_username}'")
            
            try:
                image_uploaded = False
                user = await self.client.users.register_user(
                    discord_id=discord_user_id,
                    discord_username=jellyfin_username,
                    password=password,
                )

                registration_state.increment()
                
                if registration_state.is_full():
                    await self.reattach_register_embed()

                user_id = user.get("Id")
                if not user_id:
                    return "❌ Failed to retrieve Vault+ user ID after creation."

                if profile_picture_url:
                    try:
                        image_uploaded = await self.client.avatars.upload_avatar(
                            user_id, profile_picture_url, jellyfin_username, password
                        )
                    except Exception:
                        trace = traceback.format_exc()
                        logger.exception("Upload failed")
                        await self.admin_notifier.send_admin_alert(trace, context="upload_avatar")

                has_role = any(role.id == settings.SUBSCRIBE_ROLE for role in interaction.user.roles)
                logger.info(f'Subscriber? {has_role}')

                if has_role:
                    try:
                        await self.disable_subscriber_downloads(interaction)
                    except Exception as e:
                        trace = traceback.format_exc()
                        logger.exception("Disable downloads failed")
                        await self.admin_notifier.send_admin_alert(trace, context="disable_downloads")

                await log_registered_user(
                    discord_id=discord_user_id,
                    discord_username=discord_username,
                    jellyfin_username=jellyfin_username,
                    email=email or "unknown"
                )
                
                logger.info(f'User {jellyfin_username} created on The Vault+ and profile image {'successfully' if image_uploaded else 'not'} uploaded.')

                await self.admin_notifier.send_registration_notice(
                    discord_user=self.get_user(int(discord_user_id)),
                    jellyfin_username=jellyfin_username,
                    email=email or "unknown"
                )

                await self.apply_vaultplus_role(discord_user_id, discord_username)
                stats = self.link_map.get_stats()
                logger.info(f"[VaultBot] Registration complete. Hot cache: {stats['hot_cache_size']}/{stats['max_cache_size']} entries")
  
                return (
                    f"## ✅ You are now registered on **The Vault+**!\n"
                    f"Username: `{jellyfin_username}`\n"
                    f"Password: `{password}`\n\n"
                    f"-# Linked to Discord user `{discord_username}`\n"
                    f"-# Credentials sent to `{email}`"
                )

            except DiscordAlreadyLinkedSameUsername as e:
                return f"⚠️ You're already registered as `{e.username}`.\n\n-# Forgot your password? Contact support."

            except DiscordAlreadyLinkedDifferentUsername as e:
                return f"⚠️ You're already registered as `{e.existing_username}`.\n\n-# You tried to register as `{e.requested_username}`. Contact support if you need help."

            except UsernameExistsUnlinked as e:
                return (
                    f"## 🔁 Vault+ account `{e.username}` existed, but is now linked to you.\n"
                    f"Username: `{e.username}`\n"
                    f"-# Linked to Discord user `{discord_username}`"
                )

            except UsernameTaken as e:
                return f"🚫 Username `{e.username}` is already taken. Please choose another username."

            except Exception:
                trace = traceback.format_exc()
                logger.exception("Unhandled exception in register command")
                await self.admin_notifier.send_admin_alert(trace, context="bot.register_vault_plus_user")
                return "❌ Unexpected error. Admins have been alerted."