# core/bot/cogs/subscription_tracker/tracker.py
import aiohttp
import asyncio
from discord.ext import tasks, commands
from utils.logger_factory import setup_logger
from datetime import datetime
from typing import Set

logger = setup_logger(__name__)

class ExpiredSubscriptionDisabler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track users we've already processed to avoid repeated checks
        self._processed_expired_users: Set[str] = set()

    async def cog_load(self):
        logger.info("[ExpiredSubscriptionDisabler] Cog loaded, starting task if not running.")
        if not self.disable_expired.is_running():
            self.disable_expired.start()

    def cog_unload(self):
        logger.info("[ExpiredSubscriptionDisabler] Cog unloading, cancelling task...")
        self.disable_expired.cancel()

    async def _remove_user_from_hot_cache(self, discord_id: str, jellyfin_id: str):
        """Remove user from hot cache when they're disabled"""
        try:
            if hasattr(self.bot, 'link_map') and self.bot.link_map:
                await self.bot.link_map.remove_link(jellyfin_user_id=jellyfin_id, discord_id=discord_id)
                logger.debug(f"[ExpiredSubscriptionDisabler] Removed disabled user {discord_id} from hot cache")
        except Exception as e:
            logger.debug(f"[ExpiredSubscriptionDisabler] Failed to remove user from hot cache: {e}")

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

            # Track users we process this round
            current_expired_ids = set()
            newly_processed = 0
            already_processed = 0

            for row in expired:
                discord_id = row.get("discord_user_id")
                if not discord_id:
                    continue
                
                discord_id_str = str(discord_id)
                current_expired_ids.add(discord_id_str)
                
                # Skip if we've already processed this user
                if discord_id_str in self._processed_expired_users:
                    already_processed += 1
                    continue
                
                jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(discord_id_str)
                if not jellyfin_id:
                    logger.warning(f"No Jellyfin user for Discord {discord_id}")
                    self._processed_expired_users.add(discord_id_str)
                    continue
                
                # Check if user is already disabled using Jellyfin API
                try:
                    user_data = await self.bot.client.api.get_by_jellyfin_user_id(jellyfin_id)
                    if user_data and user_data.get('Policy', {}).get('IsDisabled', False):
                        logger.debug(f"Jellyfin user {jellyfin_id} (Discord {discord_id}) already disabled, marking as processed")
                        self._processed_expired_users.add(discord_id_str)
                        # Remove from hot cache since they're disabled
                        await self._remove_user_from_hot_cache(discord_id_str, jellyfin_id)
                        already_processed += 1
                        continue
                    
                    # User is not disabled, proceed with disabling
                    await self.bot.client.users.disable_vaultplus_user(jellyfin_id)
                    logger.info(f"Disabled Vault+ account for Jellyfin user {jellyfin_id} (Discord {discord_id})")
                    
                    # Add to processed set
                    self._processed_expired_users.add(discord_id_str)
                    
                    # Remove from hot cache
                    await self._remove_user_from_hot_cache(discord_id_str, jellyfin_id)
                    
                    newly_processed += 1
                    
                except Exception as api_error:
                    logger.warning(f"Error checking/disabling user {jellyfin_id}: {api_error}")
                
                await asyncio.sleep(0.1)
            
            # Clean up processed users who are no longer in expired list (renewed subscriptions)
            before_cleanup = len(self._processed_expired_users)
            self._processed_expired_users &= current_expired_ids
            after_cleanup = len(self._processed_expired_users)
            
            if before_cleanup != after_cleanup:
                logger.info(f"[ExpiredSubscriptionDisabler] Cleaned up {before_cleanup - after_cleanup} renewed subscriptions from tracking")
            
            # Log summary only if there was activity
            if newly_processed > 0:
                logger.info(f"[ExpiredSubscriptionDisabler] Processed {newly_processed} new expired users, {already_processed} already handled")
            elif already_processed > 0 and already_processed <= 3:
                logger.debug(f"[ExpiredSubscriptionDisabler] {already_processed} users already processed")
                    
        except Exception as e:
            logger.error(f"Error disabling expired users: {e}")

    @disable_expired.before_loop
    async def before_disable(self):
        logger.info("[ExpiredSubscriptionDisabler] disable_expired about to start looping.")
        
        now = datetime.utcnow()
        # Sleep until next 5-minute mark (e.g. 00:00, 00:05, ..., 00:55)
        seconds_until_next_5min = ((5 - (now.minute % 5)) * 60) - now.second
        if seconds_until_next_5min == 0:
            seconds_until_next_5min = 300  # If exactly on the mark, sleep a whole 5 minutes
        await asyncio.sleep(seconds_until_next_5min)