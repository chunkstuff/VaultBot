# core/bot/cogs/vaultplus_admin/admin.py
import discord
import traceback
from discord.ext import commands
from discord import app_commands, Interaction
from config.settings import settings
from utils.decorators import is_staff
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class VaultPlusAdmin(commands.GroupCog, name="vaultplusadmin"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="check_account", description="Check a user's Vault+ account status")
    @app_commands.describe(user="The Discord user to check")
    @is_staff()
    async def check_account(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            discord_id = str(user.id)
            
            # Check if user has linked Jellyfin account
            jellyfin_id = await self.bot.link_map.get_jellyfin_user_id(discord_id)
            
            if not jellyfin_id:
                await interaction.followup.send(
                    f"❌ {user.mention} does not have a linked Vault+ account.",
                    ephemeral=True
                )
                return
            
            # Get Jellyfin account details
            jellyfin_user = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
            if not jellyfin_user:
                await interaction.followup.send(
                    f"⚠️ {user.mention} has a link but Jellyfin account not found (ID: {jellyfin_id})",
                    ephemeral=True
                )
                return
            
            username = jellyfin_user.get('Name', 'Unknown')
            policy = jellyfin_user.get('Policy', {})
            is_disabled = policy.get('IsDisabled', False)
            downloads_enabled = policy.get('EnableContentDownloading', True)
            
            # Check Discord roles
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
            
            # Build status embed
            embed = discord.Embed(
                title="🔍 Vault+ Account Status",
                color=discord.Color.red() if is_disabled else discord.Color.green()
            )
            
            embed.add_field(name="Discord User", value=f"{user.mention} ({user.id})", inline=False)
            embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
            embed.add_field(name="Jellyfin ID", value=f"`{jellyfin_id}`", inline=True)
            
            # Account status
            status_emoji = "🔴" if is_disabled else "🟢"
            embed.add_field(
                name="Account Status",
                value=f"{status_emoji} {'**DISABLED**' if is_disabled else 'Active'}",
                inline=False
            )
            
            # Role status
            roles_status = []
            if has_vaultplus_role:
                roles_status.append("✅ Vault+ Role")
            else:
                roles_status.append("❌ No Vault+ Role")
            
            if has_subscribe_role:
                roles_status.append("✅ Subscriber Role")
            else:
                roles_status.append("❌ No Subscriber Role")
            
            embed.add_field(name="Discord Roles", value="\n".join(roles_status), inline=False)
            
            # Downloads status
            downloads_emoji = "🔓" if downloads_enabled else "🔒"
            downloads_status = f"{downloads_emoji} {'Enabled' if downloads_enabled else 'Disabled'}"
            
            if downloads_fixed:
                downloads_status += f"\n✅ **Auto-fixed** ({action})"
            
            embed.add_field(name="Downloads", value=downloads_status, inline=False)
            
            # Only add warnings for account disabled (downloads are auto-fixed)
            if is_disabled:
                embed.add_field(name="⚠️ Issues Found", value="🔴 **Account is disabled**", inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error checking account for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(
                f"❌ Error checking account: {e}",
                ephemeral=True
            )

    @app_commands.command(name="enable_account", description="Re-enable a disabled Vault+ account")
    @app_commands.describe(user="The Discord user whose account to enable")
    @is_staff()
    async def enable_account(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            discord_id = str(user.id)
            
            # Check if user has linked Jellyfin account
            jellyfin_id = await self.bot.link_map.get_jellyfin_user_id(discord_id)
            
            if not jellyfin_id:
                await interaction.followup.send(
                    f"❌ {user.mention} does not have a linked Vault+ account.",
                    ephemeral=True
                )
                return
            
            # Get current status
            jellyfin_user = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
            if not jellyfin_user:
                await interaction.followup.send(
                    f"⚠️ Jellyfin account not found (ID: {jellyfin_id})",
                    ephemeral=True
                )
                return
            
            username = jellyfin_user.get('Name', 'Unknown')
            is_disabled = jellyfin_user.get('Policy', {}).get('IsDisabled', False)
            
            if not is_disabled:
                await interaction.followup.send(
                    f"ℹ️ Account `{username}` is already active.",
                    ephemeral=True
                )
                return
            
            # Re-enable the account using the UserService method
            await self.bot.client.users.enable_vaultplus_user(jellyfin_id)
            
            logger.info(f"Re-enabled Vault+ account '{username}' for {user} ({discord_id})")
            
            # Send success message
            embed = discord.Embed(
                title="✅ Account Re-enabled",
                description=f"Successfully re-enabled Vault+ account for {user.mention}",
                color=discord.Color.green()
            )
            embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
            embed.add_field(name="Jellyfin ID", value=f"`{jellyfin_id}`", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Notify admins
            if self.bot.admin_notifier:
                await self.bot.admin_notifier.send_generic_notice(
                    title="✅ Account Re-enabled",
                    message=f"**{username}** re-enabled for {user.mention} by <@{interaction.user.id}>",
                    color=discord.Color.green()
                )
            
        except Exception as e:
            logger.error(f"Error enabling account for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(
                f"❌ Error enabling account: {e}",
                ephemeral=True
            )

    @app_commands.command(name="fix_downloads", description="Fix download permissions based on user role")
    @app_commands.describe(user="The Discord user whose downloads to fix")
    @is_staff()
    async def fix_downloads(self, interaction: Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        try:
            discord_id = str(user.id)
            
            # Check if user has linked Jellyfin account
            jellyfin_id = await self.bot.link_map.get_jellyfin_user_id(discord_id)
            
            if not jellyfin_id:
                await interaction.followup.send(
                    f"❌ {user.mention} does not have a linked Vault+ account.",
                    ephemeral=True
                )
                return
            
            # Get current status
            jellyfin_user = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
            if not jellyfin_user:
                await interaction.followup.send(
                    f"⚠️ Jellyfin account not found (ID: {jellyfin_id})",
                    ephemeral=True
                )
                return
            
            username = jellyfin_user.get('Name', 'Unknown')
            downloads_enabled = jellyfin_user.get('Policy', {}).get('EnableContentDownloading', True)
            
            # Check if user is subscriber
            has_subscribe_role = any(role.id == settings.SUBSCRIBE_ROLE for role in user.roles)
            should_disable_downloads = has_subscribe_role
            
            # Check if already correct
            if downloads_enabled == (not should_disable_downloads):
                status = "disabled" if not downloads_enabled else "enabled"
                await interaction.followup.send(
                    f"ℹ️ Downloads already correctly {status} for `{username}`.",
                    ephemeral=True
                )
                return
            
            # Fix the downloads setting
            if should_disable_downloads:
                await self.bot.client.users.disable_downloads(jellyfin_id)
                action = "disabled"
                reason = "user is a subscriber"
            else:
                await self.bot.client.users.enable_downloads(jellyfin_id)
                action = "enabled"
                reason = "user is not a subscriber"
            
            logger.info(f"Downloads {action} for '{username}' ({discord_id}) - {reason}")
            
            # Send success message
            embed = discord.Embed(
                title=f"✅ Downloads {action.capitalize()}",
                description=f"Successfully {action} downloads for {user.mention}",
                color=discord.Color.green()
            )
            embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error fixing downloads for {user}: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send(
                f"❌ Error fixing downloads: {e}",
                ephemeral=True
            )

    @app_commands.command(name="user_info", description="Get complete information about a Vault+ user")
    @app_commands.describe(user="The Discord user to look up")
    @is_staff()
    async def user_info(self, interaction: Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)
        
        try:
            discord_id = str(user.id)
            
            # Get Jellyfin ID
            jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(discord_id)
            
            if not jellyfin_id:
                await interaction.followup.send(
                    f"❌ {user.mention} is not linked to a Vault+ account.",
                    ephemeral=True
                )
                return
            
            # Get Jellyfin user data
            jf_user = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
            
            if not jf_user:
                await interaction.followup.send(
                    f"❌ Jellyfin account not found for {user.mention}",
                    ephemeral=True
                )
                return
            
            # Get playlist count
            vault_db = self.bot.client.users.sessions.user_session_db
            playlist_rows = await vault_db.query(
                "SELECT COUNT(*) as count FROM user_playlists WHERE discord_id = ? AND is_expired = 0",
                (discord_id,)
            )
            active_playlists = playlist_rows[0]["count"] if playlist_rows else 0
            
            # Build info embed
            policy = jf_user.get("Policy", {})
            is_disabled = policy.get("IsDisabled", False)
            downloads_enabled = policy.get("EnableContentDownloading", False)
            
            # Check roles
            has_vaultplus = any(role.id == settings.VAULTPLUS_ROLE for role in user.roles)
            has_subscriber = any(role.id == settings.SUBSCRIBE_ROLE for role in user.roles)
            
            embed = discord.Embed(
                title=f"📊 User Info: {user.display_name}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="Discord",
                value=(
                    f"**ID:** `{discord_id}`\n"
                    f"**Vault+ Role:** {'✅' if has_vaultplus else '❌'}\n"
                    f"**Subscriber Role:** {'✅' if has_subscriber else '❌'}"
                ),
                inline=False
            )
            
            embed.add_field(
                name="Jellyfin",
                value=(
                    f"**Username:** `{jf_user.get('Name', 'Unknown')}`\n"
                    f"**ID:** `{jellyfin_id}`\n"
                    f"**Status:** {'🔴 Disabled' if is_disabled else '🟢 Enabled'}\n"
                    f"**Downloads:** {'✅ Enabled' if downloads_enabled else '❌ Disabled'}"
                ),
                inline=False
            )
            
            embed.add_field(
                name="Activity",
                value=(
                    f"**Active Playlists:** {active_playlists}\n"
                    f"**Last Activity:** {jf_user.get('LastActivityDate', 'Unknown')}"
                ),
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.exception(f"Error getting user info for {user}")
            await interaction.followup.send(
                f"❌ Error retrieving user info: {str(e)}",
                ephemeral=True
            )