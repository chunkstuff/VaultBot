# core/bot/cogs/subscription_tracker/tracker.py
import aiohttp
import asyncio
from discord.ext import tasks, commands
from utils.logger_factory import setup_logger
from datetime import datetime
from typing import Dict, List
from config.settings import settings

logger = setup_logger(__name__)

class SubscriptionTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track users we've already processed: {discord_id: timestamp}
        self._processed_expired_users: Dict[str, float] = {}
        self._processed_active_users: Dict[str, float] = {}

    async def cog_load(self):
        logger.info("[SubscriptionTracker] Cog loaded, starting task if not running.")
        if not self.process_subscriptions.is_running():
            self.process_subscriptions.start()

    def cog_unload(self):
        logger.info("[SubscriptionTracker] Cog unloading, cancelling task...")
        self.process_subscriptions.cancel()

    def _prune_old_entries(self, current_time: float):
        """Remove entries older than 24 hours"""
        cutoff_time = current_time - 86400
        
        expired_before = len(self._processed_expired_users)
        self._processed_expired_users = {
            discord_id: timestamp 
            for discord_id, timestamp in self._processed_expired_users.items()
            if timestamp > cutoff_time
        }
        expired_pruned = expired_before - len(self._processed_expired_users)
        
        active_before = len(self._processed_active_users)
        self._processed_active_users = {
            discord_id: timestamp 
            for discord_id, timestamp in self._processed_active_users.items()
            if timestamp > cutoff_time
        }
        active_pruned = active_before - len(self._processed_active_users)
        
        if expired_pruned > 0 or active_pruned > 0:
            logger.debug(f"[SubscriptionTracker] Pruned {expired_pruned} expired, {active_pruned} active entries")

    async def _fetch_expired_users(self) -> List[dict]:
        """Get expired users from local API"""
        url = settings.SUBSCRIPTION_ENDPOINTS["expired"]
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Expired API request failed ({resp.status})")
                    return []
                return await resp.json()

    async def _fetch_active_users(self) -> List[dict]:
        """Get newly active users from local API"""
        url = settings.SUBSCRIPTION_ENDPOINTS["active"]
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Active API request failed ({resp.status})")
                    return []
                return await resp.json()

    def _was_recently_processed_expired(self, discord_id: str, current_time: float) -> bool:
        """Check if expired user was processed within last 24 hours"""
        if discord_id not in self._processed_expired_users:
            return False
        last_processed = self._processed_expired_users[discord_id]
        hours_since = (current_time - last_processed) / 3600
        return hours_since < 24

    def _was_recently_processed_active(self, discord_id: str, current_time: float) -> bool:
        """Check if active user was processed within last 24 hours"""
        if discord_id not in self._processed_active_users:
            return False
        last_processed = self._processed_active_users[discord_id]
        hours_since = (current_time - last_processed) / 3600
        return hours_since < 24

    async def _remove_from_hot_cache(self, discord_id: str, jellyfin_id: str):
        """Remove user from hot cache"""
        try:
            if hasattr(self.bot, 'link_map') and self.bot.link_map:
                await self.bot.link_map.remove_link(jellyfin_user_id=jellyfin_id, discord_id=discord_id)
        except Exception as e:
            logger.debug(f"Failed to remove user from hot cache: {e}")

    async def _mark_processed_expired_and_cleanup(self, discord_id: str, jellyfin_id: str, current_time: float):
        """Mark expired user as processed and remove from hot cache"""
        self._processed_expired_users[discord_id] = current_time
        await self._remove_from_hot_cache(discord_id, jellyfin_id)

    async def _mark_processed_active(self, discord_id: str, current_time: float):
        """Mark active user as processed"""
        self._processed_active_users[discord_id] = current_time

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
        
        if self._was_recently_processed_expired(discord_id_str, current_time):
            return
        
        jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(discord_id_str)
        if not jellyfin_id:
            logger.warning(f"No Jellyfin user for Discord {discord_id}")
            self._processed_expired_users[discord_id_str] = current_time
            return
        
        try:
            if await self._is_user_disabled(jellyfin_id):
                logger.debug(f"Jellyfin user {jellyfin_id} already disabled")
                await self._mark_processed_expired_and_cleanup(discord_id_str, jellyfin_id, current_time)
                return
            
            await self.bot.client.users.disable_vaultplus_user(jellyfin_id)
            logger.info(f"Disabled Vault+ account for Jellyfin user {jellyfin_id} (Discord {discord_id})")
            await self._mark_processed_expired_and_cleanup(discord_id_str, jellyfin_id, current_time)
            
        except Exception as e:
            logger.warning(f"Error processing expired user {jellyfin_id}: {e}")

    async def _process_active_user(self, user_data: dict, current_time: float):
        """Process a single newly active user"""
        discord_id = user_data.get("discord_user_id")
        if not discord_id:
            return
        
        discord_id_str = str(discord_id)
        
        if self._was_recently_processed_active(discord_id_str, current_time):
            return
        
        # Check if they have a linked account first
        jellyfin_id = await self.bot.link_map.get_jellyfin_user_id(discord_id_str)
        if not jellyfin_id:
            logger.debug(f"No linked account for Discord {discord_id}, skipping")
            await self._mark_processed_active(discord_id_str, current_time)
            return
        
        try:
            # Check current status
            user_data = await self.bot.client.api.get_by_jellyfin_user_id(jellyfin_id)
            if not user_data:
                logger.warning(f"Linked Jellyfin user {jellyfin_id} not found for Discord {discord_id}")
                await self._mark_processed_active(discord_id_str, current_time)
                return
            
            username = user_data.get('Name', 'Unknown')
            is_disabled = user_data.get('Policy', {}).get('IsDisabled', False)
            
            # Already active? Nothing to do
            if not is_disabled:
                logger.debug(f"Account '{username}' for Discord {discord_id} is already active")
                await self._mark_processed_active(discord_id_str, current_time)
                return
            
            # Account exists and is disabled, reactivate it
            payload = {
                "userId": jellyfin_id,
                "IsDisabled": False,
                "AuthenticationProviderId": settings.VAULTPLUS_AUTH,
                "PasswordResetProviderId": settings.VAULTPLUS_PWRS,
            }
            
            await self.bot.client.api.post(f"/Users/{jellyfin_id}/Policy", data=payload)
            logger.info(f"Reactivated account '{username}' for Discord {discord_id}")
            
            # Notify admins
            if self.bot.admin_notifier:
                await self.bot.admin_notifier.send_generic_notice(
                    title="🔄 Account Reactivated",
                    message=f"**{username}** reactivated for <@{discord_id}>",
                    color=0x00ff00  # Green
                )
            
            await self._mark_processed_active(discord_id_str, current_time)
            
        except Exception as e:
            logger.warning(f"Error processing active user {discord_id}: {e}")

    @tasks.loop(minutes=5)
    async def process_subscriptions(self):
        """Main task to process expired and newly active users"""
        try:
            current_time = datetime.utcnow().timestamp()
            
            # Prune old entries
            self._prune_old_entries(current_time)
            
            # Get users from both endpoints
            expired_users = await self._fetch_expired_users()
            active_users = await self._fetch_active_users()
            
            # Process expired users (disable accounts)
            for user_data in expired_users:
                await self._process_expired_user(user_data, current_time)
                await asyncio.sleep(0.1)
            
            # Process newly active users (reactivate accounts)  
            for user_data in active_users:
                await self._process_active_user(user_data, current_time)
                await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Error processing subscriptions: {e}")

    @process_subscriptions.before_loop
    async def before_process_subscriptions(self):
        logger.info("[SubscriptionTracker] process_subscriptions about to start looping.")
        
        now = datetime.utcnow()
        seconds_until_next_5min = ((5 - (now.minute % 5)) * 60) - now.second
        if seconds_until_next_5min == 0:
            seconds_until_next_5min = 300
        await asyncio.sleep(seconds_until_next_5min)