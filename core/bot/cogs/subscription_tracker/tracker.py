import aiohttp
import asyncio
from discord.ext import tasks, commands
from utils.logger_factory import setup_logger
from datetime import datetime

logger = setup_logger(__name__)

class ExpiredSubscriptionDisabler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # If your discord.py version supports cog_load (pycord, nextcord, etc)
    async def cog_load(self):
        logger.info("[ExpiredSubscriptionDisabler] Cog loaded, starting task if not running.")
        if not self.disable_expired.is_running():
            self.disable_expired.start()

    def cog_unload(self):
        logger.info("[ExpiredSubscriptionDisabler] Cog unloading, cancelling task...")
        self.disable_expired.cancel()

    @tasks.loop(minutes=5)
    async def disable_expired(self):
        url = "http://localhost:4050/api/expired-subscribers"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(f"API request failed ({resp.status})")
                        return
                    expired = await resp.json()

            for row in expired:
                discord_id = row.get("discord_user_id")
                if not discord_id:
                    continue
                
                jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(str(discord_id))
                if not jellyfin_id:
                    logger.warning(f"No Jellyfin user for Discord {discord_id}")
                    continue
                
                # Check if user is already disabled using Jellyfin API
                try:
                    user_data = await self.bot.client.api.get_by_jellyfin_user_id(jellyfin_id)
                    if user_data and user_data.get('Policy', {}).get('IsDisabled', False):
                        logger.info(f"Jellyfin user {jellyfin_id} (Discord {discord_id}) already disabled, skipping")
                        continue
                    
                    # User is not disabled, proceed with disabling
                    await self.bot.client.users.disable_vaultplus_user(jellyfin_id)
                    logger.info(f"Disabled Vault+ account for Jellyfin user {jellyfin_id} (Discord {discord_id})")
                    
                except Exception as api_error:
                    logger.warning(f"Error checking/disabling user {jellyfin_id}: {api_error}")
                
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error disabling expired users: {e}")

    @disable_expired.before_loop
    async def before_disable(self):
        logger.info("[ExpiredSubscriptionDisabler] disable_expired about to start looping.")
        # await self.bot.wait_until_ready()  # Commented as requested
        now = datetime.utcnow()
        # Sleep until next 5-minute mark (e.g. 00:00, 00:05, ..., 00:55)
        seconds_until_next_5min = ((5 - (now.minute % 5)) * 60) - now.second
        if seconds_until_next_5min == 0:
            seconds_until_next_5min = 300  # If exactly on the mark, sleep a whole 5 minutes
        await asyncio.sleep(seconds_until_next_5min)
