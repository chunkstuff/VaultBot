# db/database_link_map.py
import time
import asyncio
from collections import OrderedDict
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

class HotLinkManager:
    def __init__(self, user_links_db, hot_cache_size=500, hot_ttl=3600):
        self.user_links_db = user_links_db  # UserLinksDB instance
        self.hot_cache_size = hot_cache_size
        self.hot_ttl = hot_ttl
        
        # Hot cache for recently accessed users (LRU)
        self._hot_cache = OrderedDict()  # {jellyfin_user_id: (discord_id, discord_username)}
        self._hot_reverse = OrderedDict()  # {discord_id: jellyfin_user_id}
        self._access_times = {}  # {jellyfin_user_id: timestamp}
        
        # Single-user loading cache to avoid duplicate DB queries
        self._loading = {}  # {jellyfin_user_id: Future}

    async def get_discord_info(self, jellyfin_user_id: str) -> tuple[str, str] | None:
        """Get (discord_id, discord_username) for a jellyfin user"""
        now = time.time()
        
        # Check hot cache first
        if jellyfin_user_id in self._hot_cache:
            # Move to end (most recently used) and update access time
            info = self._hot_cache.pop(jellyfin_user_id)
            self._hot_cache[jellyfin_user_id] = info
            self._access_times[jellyfin_user_id] = now
            logger.debug(f"[HotLinkManager] Cache hit for jellyfin user: {jellyfin_user_id} -> {info[0]} ({info[1]})")
            return info
        
        # Not in cache - load from database
        logger.debug(f"[HotLinkManager] Cache miss for jellyfin user: {jellyfin_user_id}, loading from database")
        info = await self._load_single_user(jellyfin_user_id)
        if info:
            self._add_to_hot_cache(jellyfin_user_id, info, now)
            logger.debug(f"[HotLinkManager] Cached new user: {jellyfin_user_id} -> {info[0]} ({info[1]})")
        else:
            logger.debug(f"[HotLinkManager] User not found in database: {jellyfin_user_id}")
        
        return info

    async def get_jellyfin_user_id(self, discord_id: str) -> str | None:
        """Get jellyfin_user_id for a discord user"""
        # Check hot reverse cache
        if discord_id in self._hot_reverse:
            jellyfin_id = self._hot_reverse[discord_id]
            # Refresh the main cache to update LRU
            await self.get_discord_info(jellyfin_id)
            logger.debug(f"[HotLinkManager] Reverse cache hit for discord user: {discord_id} -> {jellyfin_id}")
            return jellyfin_id
        
        # Not in cache - use UserLinksDB's existing method
        logger.debug(f"[HotLinkManager] Reverse cache miss for discord user: {discord_id}, querying database")
        jellyfin_id = await self.user_links_db.get_jellyfin_user(str(discord_id))
        
        if jellyfin_id:
            # Get the full info and cache it
            info = await self._get_discord_username_for_caching(discord_id, jellyfin_id)
            if info:
                self._add_to_hot_cache(jellyfin_id, info, time.time())
                logger.debug(f"[HotLinkManager] Cached reverse lookup: {discord_id} -> {jellyfin_id}")
        else:
            logger.debug(f"[HotLinkManager] Discord user not found in database: {discord_id}")
        
        return jellyfin_id

    async def get_discord_mention(self, jellyfin_user_id: str, guild) -> str:
        """Get Discord mention for a Jellyfin user"""
        info = await self.get_discord_info(jellyfin_user_id)
        if not info:
            logger.debug(f"[HotLinkManager] Could not get mention for unknown jellyfin user: {jellyfin_user_id}")
            return "Unknown"
        
        discord_id = info[0]
        mention = f"<@{discord_id}>"
        logger.debug(f"[HotLinkManager] Generated mention for {jellyfin_user_id}: {mention}")
        return mention

    async def add_link(self, jellyfin_user_id: str, discord_id: str, discord_username: str):
        """Add a new link - immediately add to hot cache"""
        info = (str(discord_id), discord_username)
        self._add_to_hot_cache(jellyfin_user_id, info, time.time())
        logger.info(f"Added new link to hot cache: {jellyfin_user_id} -> {discord_id}")

    async def link(self, jellyfin_user_id: str, discord_id: str, discord_username: str):
        """Add a new link to the database and hot cache"""
        try:
            # Add to database first
            await self.user_links_db.link_user(jellyfin_user_id, str(discord_id), discord_username)
            
            # Then add to hot cache
            info = (str(discord_id), discord_username)
            self._add_to_hot_cache(jellyfin_user_id, info, time.time())
            
            logger.info(f"[HotLinkManager] Added new link: {jellyfin_user_id} -> {discord_id} ({discord_username})")
            
        except Exception as e:
            logger.error(f"[HotLinkManager] Failed to add link {jellyfin_user_id} -> {discord_id}: {e}")
            raise

    async def remove_link(self, jellyfin_user_id: str | None = None, discord_id: str | None = None):
        """Remove a link from hot cache"""
        if jellyfin_user_id and jellyfin_user_id in self._hot_cache:
            info = self._hot_cache.pop(jellyfin_user_id)
            self._hot_reverse.pop(info[0], None)
            self._access_times.pop(jellyfin_user_id, None)
            logger.debug(f"Removed link from hot cache: {jellyfin_user_id}")
        
        if discord_id and str(discord_id) in self._hot_reverse:
            jf_id = self._hot_reverse.pop(str(discord_id))
            self._hot_cache.pop(jf_id, None)
            self._access_times.pop(jf_id, None)
            logger.debug(f"Removed link from hot cache: {discord_id}")

    def cleanup_stale_entries(self):
        """Remove entries that haven't been accessed recently"""
        cutoff = time.time() - self.hot_ttl
        to_remove = [
            uid for uid, last_time in self._access_times.items()
            if last_time < cutoff
        ]
        
        for uid in to_remove:
            if uid in self._hot_cache:
                info = self._hot_cache.pop(uid)
                self._hot_reverse.pop(info[0], None)
            self._access_times.pop(uid, None)
        
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} stale entries from hot cache")

    def _add_to_hot_cache(self, jellyfin_user_id: str, info: tuple[str, str], access_time: float):
        """Add entry to hot cache with LRU eviction"""
        # Remove if already exists (to update position)
        if jellyfin_user_id in self._hot_cache:
            old_info = self._hot_cache.pop(jellyfin_user_id)
            self._hot_reverse.pop(old_info[0], None)
        
        # Evict oldest if at capacity
        while len(self._hot_cache) >= self.hot_cache_size:
            old_jf_id, old_info = self._hot_cache.popitem(last=False)
            self._hot_reverse.pop(old_info[0], None)
            self._access_times.pop(old_jf_id, None)
        
        # Add new entry
        self._hot_cache[jellyfin_user_id] = info
        self._hot_reverse[info[0]] = jellyfin_user_id
        self._access_times[jellyfin_user_id] = access_time

    async def _load_single_user(self, jellyfin_user_id: str) -> tuple[str, str] | None:
        """Load a single user from database with deduplication"""
        # Check if already loading
        if jellyfin_user_id in self._loading:
            logger.debug(f"[HotLinkManager] Already loading {jellyfin_user_id}, waiting for result")
            return await self._loading[jellyfin_user_id]
        
        # Create future for this load
        logger.debug(f"[HotLinkManager] Starting database load for {jellyfin_user_id}")
        future = asyncio.create_task(self._do_load_single_user(jellyfin_user_id))
        self._loading[jellyfin_user_id] = future
        
        try:
            result = await future
            if result:
                logger.debug(f"[HotLinkManager] Successfully loaded {jellyfin_user_id} from database")
            else:
                logger.debug(f"[HotLinkManager] Database load returned no result for {jellyfin_user_id}")
            return result
        except Exception as e:
            logger.error(f"[HotLinkManager] Database load failed for {jellyfin_user_id}: {e}")
            return None
        finally:
            self._loading.pop(jellyfin_user_id, None)

    async def _do_load_single_user(self, jellyfin_user_id: str) -> tuple[str, str] | None:
        """Load single user from UserLinksDB by jellyfin_user_id"""
        try:
            # Since UserLinksDB doesn't have a reverse lookup method, query directly
            async with self.user_links_db._conn.execute(
                "SELECT discord_user_id, discord_username FROM user_links WHERE jellyfin_user_id = ?", 
                (jellyfin_user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    result = (str(row['discord_user_id']), row['discord_username'])
                    logger.debug(f"[HotLinkManager] Loaded user from UserLinksDB: {jellyfin_user_id} -> {result[0]} ({result[1]})")
                    return result
                
                logger.debug(f"[HotLinkManager] Jellyfin user not found in UserLinksDB: {jellyfin_user_id}")
                return None
            
        except Exception as e:
            logger.error(f"[HotLinkManager] Failed to load jellyfin user {jellyfin_user_id} from UserLinksDB: {e}")
            return None

    async def _get_discord_username_for_caching(self, discord_id: str, jellyfin_id: str) -> tuple[str, str] | None:
        """Get discord username to complete the cache entry"""
        try:
            async with self.user_links_db._conn.execute(
                "SELECT discord_username FROM user_links WHERE discord_user_id = ?", 
                (str(discord_id),)
            ) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    result = (str(discord_id), row['discord_username'])
                    logger.debug(f"[HotLinkManager] Resolved username for caching: {discord_id} -> {result[1]}")
                    return result
                
                logger.debug(f"[HotLinkManager] Discord user not found for username lookup: {discord_id}")
                return None
                
        except Exception as e:
            logger.error(f"[HotLinkManager] Failed to get username for discord {discord_id}: {e}")
            return None

    def get_stats(self) -> dict:
        """Get cache statistics for monitoring"""
        now = time.time()
        recent_count = sum(1 for t in self._access_times.values() if now - t < 300)  # Active in last 5 min
        
        stats = {
            'hot_cache_size': len(self._hot_cache),
            'max_cache_size': self.hot_cache_size,
            'cache_utilization': len(self._hot_cache) / self.hot_cache_size,
            'recently_active_users': recent_count,
            'oldest_entry_age': int(now - min(self._access_times.values())) if self._access_times else 0
        }
        
        logger.debug(f"[HotLinkManager] Cache stats: {stats['hot_cache_size']}/{stats['max_cache_size']} entries, "
                    f"{stats['recently_active_users']} recently active, "
                    f"{stats['cache_utilization']:.1%} utilization")
        
        return stats

    async def user_exists(self, jellyfin_user_id: str) -> bool:
        """Check if a jellyfin user exists in the database"""
        info = await self.get_discord_info(jellyfin_user_id)
        return info is not None