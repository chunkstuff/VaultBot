# core/bot/cogs/vaultplus_admin/admin.py
import discord
import traceback
from discord.ext import commands
from discord import app_commands, Interaction
from config.settings import settings
from utils.decorators import is_staff
from utils.logger_factory import setup_logger
from .embeds import (
    create_account_status_embed,
    create_account_enabled_embed,
    create_downloads_fixed_embed,
    create_user_info_embed,
    create_password_reset_embed,
    create_password_reset_dm_embed,
)

logger = setup_logger(__name__)

class VaultPlusAdmin(commands.GroupCog, name="vault"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_jellyfin_id(self, interaction: Interaction, user: discord.User) -> str | None:
        """Get jellyfin_id for user, send error message if not found"""
        jellyfin_id = await self.bot.link_map.get_jellyfin_user_id(str(user.id))
        if not jellyfin_id:
            await interaction.followup.send(
                f"❌ {user.mention} does not have a linked Vault+ account.",
                ephemeral=True
            )
        return jellyfin_id

    async def _get_jellyfin_user(self, interaction: Interaction, jellyfin_id: str) -> dict | None:
        """Get jellyfin user data, send error message if not found"""
        jellyfin_user = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
        if not jellyfin_user:
            await interaction.followup.send(
                f"⚠️ Jellyfin account not found (ID: {jellyfin_id})",
                ephemeral=True
            )
        return jellyfin_user

    @app_commands.command(name="check_account", description="Check a user's Vault+ account status")
    @app_commands.describe(user="The Discord user to check")
    @is_staff()
    async def check_account(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            jellyfin_id = await self._get_jellyfin_id(interaction, user)
            if not jellyfin_id:
                return
            
            jellyfin_user = await self._get_jellyfin_user(interaction, jellyfin_id)
            if not jellyfin_user:
                return
            
            discord_id = str(user.id)
            
            username = jellyfin_user.get('Name', 'Unknown')
            policy = jellyfin_user.get('Policy', {})
            is_disabled = policy.get('IsDisabled', False)
            downloads_enabled = policy.get('EnableContentDownloading', True)
            
            has_subscribe_role = any(role.id == settings.SUBSCRIBE_ROLE for role in user.roles)
            has_vaultplus_role = any(role.id == settings.VAULTPLUS_ROLE for role in user.roles)
            
            # Auto-fix downloads if needed
            should_disable_downloads = has_subscribe_role
            downloads_mismatch = downloads_enabled == should_disable_downloads
            downloads_fixed = False
            
            if downloads_mismatch:
                try:
                    if should_disable_downloads:
                        await self.bot.client.users.disable_downloads(jellyfin_id)
                        downloads_enabled = False
                        action = "disabled"
                    else:
                        await self.bot.client.users.enable_downloads(jellyfin_id)
                        downloads_enabled = True
                        action = "enabled"
                    
                    downloads_fixed = True
                    reason = "user is a subscriber" if should_disable_downloads else "user is not a subscriber"
                    logger.info(f"Auto-fixed downloads ({action}) for '{username}' ({discord_id}) - {reason}")
                except Exception as e:
                    logger.error(f"Failed to auto-fix downloads for {username}: {e}")
            
            embed = create_account_status_embed(
                user, username, jellyfin_id, is_disabled, downloads_enabled,
                has_vaultplus_role, has_subscribe_role, downloads_fixed
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error checking account for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(f"❌ Error checking account: {e}", ephemeral=True)

    @app_commands.command(name="enable_account", description="Re-enable a disabled Vault+ account")
    @app_commands.describe(user="The Discord user whose account to enable")
    @is_staff()
    async def enable_account(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            jellyfin_id = await self._get_jellyfin_id(interaction, user)
            if not jellyfin_id:
                return
            
            jellyfin_user = await self._get_jellyfin_user(interaction, jellyfin_id)
            if not jellyfin_user:
                return
            
            discord_id = str(user.id)
            
            username = jellyfin_user.get('Name', 'Unknown')
            is_disabled = jellyfin_user.get('Policy', {}).get('IsDisabled', False)
            
            if not is_disabled:
                await interaction.followup.send(
                    f"ℹ️ Account `{username}` is already active.",
                    ephemeral=True
                )
                return
            
            await self.bot.client.users.enable_vaultplus_user(jellyfin_id)
            logger.info(f"Re-enabled Vault+ account '{username}' for {user} ({discord_id})")
            
            embed = create_account_enabled_embed(user, username, jellyfin_id)
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            if self.bot.admin_notifier:
                await self.bot.admin_notifier.send_generic_notice(
                    title="✅ Account Re-enabled",
                    message=f"**{username}** re-enabled for {user.mention} by <@{interaction.user.id}>",
                    color=discord.Color.green()
                )
            
        except Exception as e:
            logger.error(f"Error enabling account for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(f"❌ Error enabling account: {e}", ephemeral=True)

    @app_commands.command(name="fix_downloads", description="Fix download permissions based on user role")
    @app_commands.describe(user="The Discord user whose downloads to fix")
    @is_staff()
    async def fix_downloads(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            jellyfin_id = await self._get_jellyfin_id(interaction, user)
            if not jellyfin_id:
                return
            
            jellyfin_user = await self._get_jellyfin_user(interaction, jellyfin_id)
            if not jellyfin_user:
                return
            
            discord_id = str(user.id)
            
            username = jellyfin_user.get('Name', 'Unknown')
            downloads_enabled = jellyfin_user.get('Policy', {}).get('EnableContentDownloading', True)
            
            has_subscribe_role = any(role.id == settings.SUBSCRIBE_ROLE for role in user.roles)
            should_disable_downloads = has_subscribe_role
            
            if downloads_enabled == (not should_disable_downloads):
                status = "disabled" if not downloads_enabled else "enabled"
                await interaction.followup.send(
                    f"ℹ️ Downloads already correctly {status} for `{username}`.",
                    ephemeral=True
                )
                return
            
            if should_disable_downloads:
                await self.bot.client.users.disable_downloads(jellyfin_id)
                action = "disabled"
                reason = "user is a subscriber"
            else:
                await self.bot.client.users.enable_downloads(jellyfin_id)
                action = "enabled"
                reason = "user is not a subscriber"
            
            logger.info(f"Downloads {action} for '{username}' ({discord_id}) - {reason}")
            
            embed = create_downloads_fixed_embed(user, username, action, reason)
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error fixing downloads for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(f"❌ Error fixing downloads: {e}", ephemeral=True)

    @app_commands.command(name="user_info", description="Get complete information about a Vault+ user")
    @app_commands.describe(user="The Discord user to look up")
    @is_staff()
    async def user_info(self, interaction: Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)
        
        try:
            from ..makemeworseplus.playlist_db import count_active_playlists
            
            jellyfin_id = await self._get_jellyfin_id(interaction, user)
            if not jellyfin_id:
                return
            
            jf_user = await self._get_jellyfin_user(interaction, jellyfin_id)
            if not jf_user:
                return
            
            discord_id = str(user.id)
            
            vault_db = self.bot.client.users.sessions.user_session_db
            active_playlists = await count_active_playlists(vault_db, discord_id)
            
            policy = jf_user.get("Policy", {})
            is_disabled = policy.get("IsDisabled", False)
            downloads_enabled = policy.get("EnableContentDownloading", False)
            has_vaultplus = any(role.id == settings.VAULTPLUS_ROLE for role in user.roles)
            has_subscriber = any(role.id == settings.SUBSCRIBE_ROLE for role in user.roles)
            
            embed = create_user_info_embed(
                user, jf_user, jellyfin_id, is_disabled, downloads_enabled,
                has_vaultplus, has_subscriber, active_playlists
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.exception(f"Error getting user info for {user}")
            await interaction.followup.send(f"❌ Error retrieving user info: {str(e)}", ephemeral=True)

    @app_commands.command(name="reset_password", description="Reset a user's Vault+ password")
    @app_commands.describe(user="The Discord user whose password to reset")
    @is_staff()
    async def reset_password(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            jellyfin_id = await self._get_jellyfin_id(interaction, user)
            if not jellyfin_id:
                return
            
            jellyfin_user = await self._get_jellyfin_user(interaction, jellyfin_id)
            if not jellyfin_user:
                return
            
            username = jellyfin_user.get('Name', 'Unknown')
            result = await self.bot.client.users.reset_password(jellyfin_id)
            
            if not result.get('success'):
                error = result.get('error', 'Unknown error')
                await interaction.followup.send(f"❌ Failed to reset password: {error}", ephemeral=True)
                return
            
            new_password = result.get('new_password')
            
            # Try to DM user
            dm_sent = False
            try:
                dm_embed = create_password_reset_dm_embed(username, new_password)
                await user.send(embed=dm_embed)
                dm_sent = True
                logger.info(f"Password reset for '{username}' - credentials sent via DM")
            except discord.Forbidden:
                logger.warning(f"Could not DM {user} - showing credentials to staff instead")
            
            staff_embed = create_password_reset_embed(user, username, new_password, dm_sent)
            await interaction.followup.send(embed=staff_embed, ephemeral=True)
            
            if self.bot.admin_notifier:
                await self.bot.admin_notifier.send_generic_notice(
                    title="🔑 Password Reset",
                    message=f"Password reset for **{username}** ({user.mention}) by <@{interaction.user.id}>",
                    color=discord.Color.gold()
                )
            
        except Exception as e:
            logger.error(f"Error resetting password for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(f"❌ Error resetting password: {e}", ephemeral=True)