# utils/decorators.py
from functools import wraps
from config.settings import settings
from utils.logger_factory import setup_logger
import discord
import traceback
import asyncio

logger = setup_logger(__name__)


def handle_exceptions(func):
    """
    Decorator that wraps functions in a try-except block to catch and log unexpected errors.
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"unexpected error! {e}")
            logger.error(traceback.format_exc())
            raise  # Re-raise the exception after logging
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"unexpected error! {e}")
            logger.error(traceback.format_exc())
            raise  # Re-raise the exception after logging
    
    # Return appropriate wrapper based on whether function is async or not
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def _has_permission(interaction: discord.Interaction, allowed_user_ids: set[int], allowed_role_ids: set[int] = None) -> bool:
    """
    Internal helper to check if user has permission.
    
    Args:
        interaction: Discord interaction
        allowed_user_ids: Set of allowed user IDs (owner, developer, etc)
        allowed_role_ids: Optional set of allowed role IDs
    
    Returns:
        True if user has permission, False otherwise
    """
    # Check user IDs first (fastest)
    if interaction.user.id in allowed_user_ids:
        return True
    
    # Check roles if provided
    if allowed_role_ids:
        user_role_ids = {role.id for role in interaction.user.roles}
        if allowed_role_ids & user_role_ids:  # If any allowed role is present
            return True
    
    return False


def _require_permission(allowed_user_ids: set[int], allowed_role_ids: set[int] = None):
    """
    Internal decorator factory for permission checking.
    
    Args:
        allowed_user_ids: Set of allowed user IDs
        allowed_role_ids: Optional set of allowed role IDs
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            if not _has_permission(interaction, allowed_user_ids, allowed_role_ids):
                await interaction.response.send_message("🚫 You are not authorised.", ephemeral=True)
                return
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator


def is_authorised():
    """
    Restrict command to owner and developer only.
    Use for sensitive administrative commands.
    """
    return _require_permission(
        allowed_user_ids={settings.DEVELOPER_ID, settings.OWNER_ID}
    )


def is_staff():
    """
    Allow command access to staff members, owner, and developer.
    Staff includes: Owner, Developer, Staff role, Junior Staff role.
    Use for moderation and management commands.
    """
    return _require_permission(
        allowed_user_ids={settings.DEVELOPER_ID, settings.OWNER_ID},
        allowed_role_ids={settings.STAFF_ROLE, settings.JUNIOR_STAFF_ROLE}
    )

def add_getworse_promotion(func):
    """
    Decorator to add Get Worse channel promotion field as the last field in embed.
    Use on embed creation functions to encourage playlist creation.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        embed = func(*args, **kwargs)
        # Add promotion field as the very last field
        embed.add_field(
            name="",
            value=f"👀 Want your own playlist? <#{settings.WORSE_PLUS_CHANNEL}>",
            inline=False
        )
        return embed
    return wrapper