# core/bot/cogs/subscription_tracker/tracker.py
import aiohttp
import asyncio
from discord.ext import tasks, commands
from utils.logger_factory import setup_logger
from datetime import datetime
from typing import Dict, List

logger = setup_logger(__name__)

class ExpiredSubscriptionDisabler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track users we've already processed: {discord_id: timestamp}
        self._processed_expired_users: Dict[str, float] = {}

    async def cog_load(self):
        logger.info("[ExpiredSubscriptionDisabler] Cog loaded, starting task if not running.")
        if not self.disable_expired.is_running():
            self.disable_expired.start()

    def cog_unload(self):
        logger.info("[ExpiredSubscriptionDisabler] Cog unloading, cancelling task...")
        self.disable_expired.cancel()

    def _prune_old_entries(self, current_time: float):
        """Remove entries older than 24 hours"""
        cutoff_time = current_time - 86400
        self._processed_expired_users = {
            discord_id: timestamp 
            for discord_id, timestamp in self._processed_expired_users.items()
            if timestamp > cutoff_time
        }

    async def _fetch_expired_users(self) -> List[dict]:
        """Get expired users from local API"""
        url = "http://localhost:4050/api/expired-subscribers"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"API request failed ({resp.status})")
                    return []
                return await resp.json()

    def _was_recently_processed(self, discord_id: str, current_time: float) -> bool:
        """Check if processed within last 24 hours"""
        if discord_id not in self._processed_expired_users:
            return False
        last_processed = self._processed_expired_users[discord_id]
        hours_since = (current_time - last_processed) / 3600
        return hours_since < 24

    async def _remove_from_hot_cache(self, discord_id: str, jellyfin_id: str):
        """Remove user from hot cache"""
        try:
            if hasattr(self.bot, 'link_map') and self.bot.link_map:
                await self.bot.link_map.remove_link(jellyfin_user_id=jellyfin_id, discord_id=discord_id)
        except Exception as e:
            logger.debug(f"Failed to remove user from hot cache: {e}")

    async def _mark_processed_and_cleanup(self, discord_id: str, jellyfin_id: str, current_time: float):
        """Mark user as processed and remove from hot cache"""
        self._processed_expired_users[discord_id] = current_time
        await self._remove_from_hot_cache(discord_id, jellyfin_id)

    async def _is_user_disabled(self, jellyfin_id: str) -> bool:
        """Check if Jellyfin user is already disabled"""
        user_data = await self.bot.client.api.get_by_jellyfin_user_id(jellyfin_id)
        if not user_data:
            return False
        return user_data.get('Policy', {}).get('IsDisabled', False)

    async def _process_expired_user(self, user_data: dict, current_time: float):
        """Process a single expired user"""
        discord_id = user_data.get("discord_user_id")
        if not discord_id:
            return
        
        discord_id_str = str(discord_id)
        
        if self._was_recently_processed(discord_id_str, current_time):
            return
        
        jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(discord_id_str)
        if not jellyfin_id:
            logger.warning(f"No Jellyfin user for Discord {discord_id}")
            self._processed_expired_users[discord_id_str] = current_time
            return
        
        try:
            if await self._is_user_disabled(jellyfin_id):
                logger.debug(f"Jellyfin user {jellyfin_id} already disabled")
                await self._mark_processed_and_cleanup(discord_id_str, jellyfin_id, current_time)
                return
            
            await self.bot.client.users.disable_vaultplus_user(jellyfin_id)
            logger.info(f"Disabled Vault+ account for Jellyfin user {jellyfin_id} (Discord {discord_id})")
            await self._mark_processed_and_cleanup(discord_id_str, jellyfin_id, current_time)
            
        except Exception as e:
            logger.warning(f"Error processing user {jellyfin_id}: {e}")

    @tasks.loop(minutes=5)
    async def disable_expired(self):
        """Main task to disable expired users"""
        try:
            current_time = datetime.utcnow().timestamp()
            
            self._prune_old_entries(current_time)
            expired_users = await self._fetch_expired_users()
            
            for user_data in expired_users:
                await self._process_expired_user(user_data, current_time)
                await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Error disabling expired users: {e}")

    @disable_expired.before_loop
    async def before_disable(self):
        logger.info("[ExpiredSubscriptionDisabler] disable_expired about to start looping.")
        
        now = datetime.utcnow()
        seconds_until_next_5min = ((5 - (now.minute % 5)) * 60) - now.second
        if seconds_until_next_5min == 0:
            seconds_until_next_5min = 300
        await asyncio.sleep(seconds_until_next_5min)