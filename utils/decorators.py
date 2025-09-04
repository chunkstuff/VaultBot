# utils/decorators.py
from functools import wraps
from config.settings import settings
from utils.logger_factory import setup_logger
import discord
import traceback
import asyncio

# Get logger instance
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

def is_authorised():
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            if interaction.user.id not in {settings.DEVELOPER_ID, settings.OWNER_ID}:
                await interaction.response.send_message("🚫 You are not authorised.", ephemeral=True)
                return
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator