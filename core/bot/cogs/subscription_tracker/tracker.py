# core/bot/cogs/subscription_tracker/tracker.py
import aiohttp
import asyncio
from discord.ext import tasks, commands
from utils.logger_factory import setup_logger
from datetime import datetime
from typing import Dict, List
from config.settings import settings
from zoneinfo import ZoneInfo

logger = setup_logger(__name__)

class SubscriptionTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track users we've already processed: {discord_id: timestamp}
        self._processed_expired_users: Dict[str, float] = {}
        self._processed_active_users: Dict[str, float] = {}
        self._processed_vault_upgrades: Dict[str, float] = {}

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
        
        pruned = {}
        for name, cache in [
            ('expired', self._processed_expired_users),
            ('active', self._processed_active_users),
            ('vault', self._processed_vault_upgrades)
        ]:
            before = len(cache)
            for discord_id in list(cache.keys()):
                if cache[discord_id] <= cutoff_time:
                    del cache[discord_id]
            
            if count := (before - len(cache)):
                pruned[name] = count
        
        if pruned:
            msg = ', '.join(f"{count} {name}" for name, count in pruned.items())
            logger.debug(f"[SubscriptionTracker] Pruned {msg} entries")

    async def _fetch_from_endpoint(self, endpoint_key: str) -> List[dict]:
        """Generic method to fetch data from subscription API endpoints"""
        url = settings.SUBSCRIPTION_ENDPOINTS[endpoint_key]
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"{endpoint_key.replace('_', ' ').title()} API request failed ({resp.status})")
                    return []
                return await resp.json()

    async def _fetch_expired_users(self) -> List[dict]:
        """Get expired users from local API"""
        return await self._fetch_from_endpoint("expired")

    async def _fetch_active_users(self) -> List[dict]:
        """Get newly active users from local API"""
        return await self._fetch_from_endpoint("active")

    async def _fetch_vault_upgrades(self) -> List[dict]:
        """Get users who upgraded to Vault from local API"""
        return await self._fetch_from_endpoint("vault_upgrades")

    def _was_recently_processed(self, discord_id: str, current_time: float, cache: Dict[str, float]) -> bool:
        """Check if user was processed within last 24 hours"""
        if discord_id not in cache:
            return False
        hours_since = (current_time - cache[discord_id]) / 3600
        return hours_since < 24

    def _was_recently_processed_expired(self, discord_id: str, current_time: float) -> bool:
        """Check if expired user was processed within last 24 hours"""
        return self._was_recently_processed(discord_id, current_time, self._processed_expired_users)

    def _was_recently_processed_active(self, discord_id: str, current_time: float) -> bool:
        """Check if active user was processed within last 24 hours"""
        return self._was_recently_processed(discord_id, current_time, self._processed_active_users)

    def _was_recently_processed_vault_upgrade(self, discord_id: str, current_time: float) -> bool:
        """Check if vault upgrade was processed within last 24 hours"""
        return self._was_recently_processed(discord_id, current_time, self._processed_vault_upgrades)

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
        user_data = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
        if not user_data:
            return False
        return user_data.get('Policy', {}).get('IsDisabled', False)

    async def _user_has_vault_access(self, discord_id: str) -> bool:
        """Check if user has Vault access via API"""
        try:
            url = f"{settings.SUBSCRIPTION_ENDPOINTS['vault_check']}/{discord_id}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(f"Vault check API request failed ({resp.status}) for {discord_id}")
                        return False
                    
                    data = await resp.json()
                    return data.get("has_vault", False)
        except Exception as e:
            logger.error(f"Error checking vault access for {discord_id}: {e}")
            return False

    async def _process_expired_user(self, user_data: dict, current_time: float):
        """Process a single expired user"""
        discord_id = user_data.get("discord_user_id")
        if not discord_id:
            return
        
        discord_id_str = str(discord_id)
        
        if self._was_recently_processed_expired(discord_id_str, current_time):
            return
        
        # Check if user has Vault access - SKIP if they do
        if await self._user_has_vault_access(discord_id_str):
            logger.info(f"Skipping expiry for Discord {discord_id} - user has Vault access")
            self._processed_expired_users[discord_id_str] = current_time
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
            
            # Returns Dict[str, Any]
            await self.bot.client.users.disable_vaultplus_user(jellyfin_id)
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
        
        # Returns Optional[str]
        jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(discord_id_str)
        if not jellyfin_id:
            logger.debug(f"No linked account for Discord {discord_id}, skipping")
            await self._mark_processed_active(discord_id_str, current_time)
            return
        
        try:
            # Returns Dict[str, Any]
            user_data = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
            if not user_data:
                logger.warning(f"Linked Jellyfin user {jellyfin_id} not found for Discord {discord_id}")
                await self._mark_processed_active(discord_id_str, current_time)
                return
            
            username = user_data.get('Name', 'Unknown')
            is_disabled = user_data.get('Policy', {}).get('IsDisabled', False)
            
            if not is_disabled:
                logger.debug(f"Account '{username}' for Discord {discord_id} is already active")
                await self._mark_processed_active(discord_id_str, current_time)
                return
            
            # Check if user has subscriber role
            guild = self.bot.get_guild(settings.GUILD_ID)
            member = guild.get_member(int(discord_id)) if guild else None
            has_subscriber_role = member and any(role.id == settings.SUBSCRIBE_ROLE for role in member.roles)
            
            # Returns Dict[str, Any]
            await self.bot.client.users.enable_vaultplus_user(jellyfin_id)
            
            # Returns Dict[str, Any]
            if has_subscriber_role:
                await self.bot.client.users.disable_downloads(jellyfin_id)
                download_status = "disabled"
            else:
                await self.bot.client.users.enable_downloads(jellyfin_id)
                download_status = "enabled"
            
            logger.info(f"Reactivated account '{username}' for Discord {discord_id} (downloads {download_status})")
            
            # Notify admins with timestamp
            if self.bot.admin_notifier:
                resubscribed_at = datetime.now(ZoneInfo("Europe/London"))
                timestamp = int(resubscribed_at.timestamp())
                
                await self.bot.admin_notifier.send_generic_notice(
                    title="🔄 Account Reactivated",
                    message=f"**{username}** reactivated for <@{discord_id}> (downloads {download_status})\n**Resubscribed at:** <t:{timestamp}:F>",
                    color=0x00ff00
                )
            
            await self._mark_processed_active(discord_id_str, current_time)
            
        except Exception as e:
            logger.warning(f"Error processing active user {discord_id}: {e}")

    async def _process_vault_upgrade(self, upgrade_data: dict, current_time: float):
        """Enable downloads for a user who upgraded to Vault"""
        discord_id = upgrade_data.get("discord_user_id")
        discord_username = upgrade_data.get("discord_username", "Unknown")
        
        if not discord_id:
            return
        
        discord_id_str = str(discord_id)
        
        if self._was_recently_processed_vault_upgrade(discord_id_str, current_time):
            return
        
        try:
            # Returns Optional[str]
            jellyfin_id = await self.bot.client.users.get_jellyfin_user_id(discord_id_str)
            if not jellyfin_id:
                logger.debug(f"No Jellyfin account for Discord {discord_id}, skipping vault upgrade")
                self._processed_vault_upgrades[discord_id_str] = current_time
                return
            
            # Returns Dict[str, Any]
            user_data = await self.bot.client.users.get_user_by_jellyfin_id(jellyfin_id)
            if not user_data:
                logger.warning(f"Jellyfin user {jellyfin_id} not found for Discord {discord_id}")
                self._processed_vault_upgrades[discord_id_str] = current_time
                return
            
            username = user_data.get('Name', discord_username)
            downloads_enabled = user_data.get('Policy', {}).get('EnableContentDownloading', False)
            
            if downloads_enabled:
                logger.debug(f"Downloads already enabled for {username} (Discord {discord_id})")
                self._processed_vault_upgrades[discord_id_str] = current_time
                return
            
            # Returns Dict[str, Any]
            await self.bot.client.users.enable_downloads(jellyfin_id)
            logger.info(f"Enabled downloads for Vault upgrade: {username} (Discord {discord_id})")
            
            # Notify admins with timestamp
            if self.bot.admin_notifier:
                upgraded_at = datetime.now(ZoneInfo("Europe/London"))
                timestamp = int(upgraded_at.timestamp())
                
                await self.bot.admin_notifier.send_generic_notice(
                    title="⬆️ Vault Upgrade",
                    message=f"**{username}** upgraded to Vault - downloads enabled for <@{discord_id}>\n**Upgraded at:** <t:{timestamp}:F>",
                    color=0xFFD700
                )
            
            self._processed_vault_upgrades[discord_id_str] = current_time
            
        except Exception as e:
            logger.warning(f"Error processing vault upgrade for {discord_id}: {e}")

    @tasks.loop(minutes=5)
    async def process_subscriptions(self):
        """Main task to process expired, active, and vault upgrade users"""
        if settings.TEST_MODE:
            logger.debug("[TEST_MODE] Skipping subscription processing - test mode active")
            return
            
        try:
            current_time = datetime.utcnow().timestamp()
            self._prune_old_entries(current_time)
            
            expired_users = await self._fetch_expired_users()
            active_users = await self._fetch_active_users()
            vault_upgrades = await self._fetch_vault_upgrades()
            
            for user_data in expired_users:
                await self._process_expired_user(user_data, current_time)
                await asyncio.sleep(0.1)
            
            for user_data in active_users:
                await self._process_active_user(user_data, current_time)
                await asyncio.sleep(0.1)
            
            for upgrade_data in vault_upgrades:
                await self._process_vault_upgrade(upgrade_data, current_time)
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