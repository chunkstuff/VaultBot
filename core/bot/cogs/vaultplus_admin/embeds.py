# core/bot/cogs/vaultplus_admin/embeds.py
import discord

def create_account_status_embed(user, username, jellyfin_id, is_disabled, downloads_enabled,
                                has_vaultplus_role, has_subscribe_role, downloads_fixed):
    """Build account status embed"""
    embed = discord.Embed(
        title="🔍 Vault+ Account Status",
        color=discord.Color.red() if is_disabled else discord.Color.green()
    )
    
    embed.add_field(name="Discord User", value=f"{user.mention} ({user.id})", inline=False)
    embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
    embed.add_field(name="Jellyfin ID", value=f"`{jellyfin_id}`", inline=True)
    
    status_emoji = "🔴" if is_disabled else "🟢"
    embed.add_field(
        name="Account Status",
        value=f"{status_emoji} {'**DISABLED**' if is_disabled else 'Active'}",
        inline=False
    )
    
    roles_status = []
    roles_status.append("✅ Vault+ Role" if has_vaultplus_role else "❌ No Vault+ Role")
    roles_status.append("✅ Subscriber Role" if has_subscribe_role else "❌ No Subscriber Role")
    embed.add_field(name="Discord Roles", value="\n".join(roles_status), inline=False)
    
    downloads_emoji = "🔓" if downloads_enabled else "🔒"
    downloads_status = f"{downloads_emoji} {'Enabled' if downloads_enabled else 'Disabled'}"
    if downloads_fixed:
        downloads_status += f"\n✅ **Auto-fixed** ({'disabled' if not downloads_enabled else 'enabled'})"
    embed.add_field(name="Downloads", value=downloads_status, inline=False)
    
    if is_disabled:
        embed.add_field(name="⚠️ Issues Found", value="🔴 **Account is disabled**", inline=False)
    
    return embed

def create_account_enabled_embed(user, username, jellyfin_id):
    """Build account re-enabled embed"""
    embed = discord.Embed(
        title="✅ Account Re-enabled",
        description=f"Successfully re-enabled Vault+ account for {user.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
    embed.add_field(name="Jellyfin ID", value=f"`{jellyfin_id}`", inline=True)
    return embed

def create_downloads_fixed_embed(user, username, action, reason):
    """Build downloads fixed embed"""
    embed = discord.Embed(
        title=f"✅ Downloads {action.capitalize()}",
        description=f"Successfully {action} downloads for {user.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    return embed

def create_user_info_embed(user, jf_user, jellyfin_id, is_disabled, downloads_enabled,
                           has_vaultplus, has_subscriber, active_playlists):
    """Build user info embed"""
    embed = discord.Embed(
        title=f"📊 User Info: {user.display_name}",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="Discord",
        value=(
            f"**ID:** `{user.id}`\n"
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
    
    return embed

def create_password_reset_embed(user, username, new_password, dm_sent):
    """Build password reset embed for staff"""
    if dm_sent:
        embed = discord.Embed(
            title="✅ Password Reset",
            description=f"Successfully reset password for {user.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Jellyfin Username", value=f"`{username}`", inline=True)
        embed.add_field(name="Credentials Sent", value="✅ Via DM", inline=True)
    else:
        embed = discord.Embed(
            title="✅ Password Reset",
            description=(
                f"Successfully reset password for {user.mention}\n\n"
                f"⚠️ **Could not DM user** - please share these credentials:\n\n"
                f"**Username:** `{username}`\n"
                f"**New Password:** `{new_password}`\n"
                f"**Login:** https://members.thevault.locker"
            ),
            color=discord.Color.gold()
        )
    
    return embed

def create_password_reset_dm_embed(username, new_password):
    """Build password reset embed for user DM"""
    embed = discord.Embed(
        title="🔑 Vault+ Password Reset",
        description=(
            f"Your Vault+ password has been reset by a staff member.\n\n"
            f"**Username:** `{username}`\n"
            f"**New Password:** `{new_password}`\n\n"
            f"**Login:** https://members.thevault.locker"
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text="Please change your password after logging in.")
    return embed