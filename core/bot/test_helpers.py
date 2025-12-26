# core/bot/test_helpers.py
"""Helper functions for test mode support"""

import discord
from config.settings import settings
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)


def get_guild(bot: discord.Client) -> discord.Guild | None:
    """
    Get the appropriate guild based on TEST_MODE.
    
    In production: Returns the specific guild by GUILD_ID
    In test mode: Returns the first available guild (assumes bot is only in test server)
    
    Args:
        bot: Discord bot client
        
    Returns:
        Guild object or None if not found
    """
    if settings.TEST_MODE:
        guild = bot.guilds[0] if bot.guilds else None
        if guild:
            logger.debug(f"[TEST_MODE] Using guild: {guild.name} (ID: {guild.id})")
        return guild
    
    return discord.utils.get(bot.guilds, id=settings.GUILD_ID)