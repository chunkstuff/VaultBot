# core/bot/cogs/makemeworseplus/excluded_items_cache.py

import time
from urllib.parse import urlencode
from utils.logger_factory import setup_logger
from utils.decorators import handle_exceptions

logger = setup_logger(__name__)

# Excluded from base playlists
EXCLUDED_COLLECTIONS = {
    "hypnopills",          # matches "Hypnopills 💊"
    "hypnobullets",        # matches "Sir's Hypnobullets"
    "glitched files",      # matches "Glitched Files 💿"
    "soundscapes",         # matches "Sir's Soundscapes"
    "sleepers",            # matches "The Venus Sleepers"
}

LULLABY_RUNTIME_THRESHOLD = 7200  # 2 hours in seconds
CACHE_DURATION = 172800  # 48 hours in seconds
TICKS_PER_SECOND = 10_000_000


class ExcludedItemsCache:
    """Cache for items that should be excluded from base playlist generation."""
    
    def __init__(self):
        self._cache: set[str] | None = None
        self._cache_time: float | None = None
    
    def _is_cache_valid(self) -> bool:
        """Check if the cache is still valid."""
        if self._cache is None or self._cache_time is None:
            return False
        return time.time() - self._cache_time < CACHE_DURATION
    
    @handle_exceptions
    async def get_excluded_ids(self, jellyfin_client, force_refresh: bool = False) -> set[str]:
        """
        Get a cached set of item IDs that should be excluded from base playlists.
        Cache expires after 48 hours or can be force refreshed.
        
        Excludes:
        - Files over 2 hours (lullabies/sleepers)
        - Albums containing: Hypnopill, Hypnobullet, Glitched files, Soundscapes
        - File names containing: Lullaby, Sleeper
        """
        # Return cached result if valid
        if not force_refresh and self._is_cache_valid():
            logger.debug(f"[excluded_items] Using cached list ({len(self._cache)} items)")
            return self._cache
        
        # Build fresh excluded list
        logger.info("[excluded_items] Building excluded items list...")
        query = urlencode({
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "Fields": "Name,Album,RunTimeTicks"
        })
        response = await jellyfin_client.api.get(f"/Items?{query}")
        all_items = response.get("Items", [])
        
        excluded_ids = set()
        
        for item in all_items:
            # Check runtime - anything 2hr+ is excluded
            runtime_ticks = item.get("RunTimeTicks", 0)
            runtime_seconds = runtime_ticks / TICKS_PER_SECOND
            if runtime_seconds >= LULLABY_RUNTIME_THRESHOLD:
                excluded_ids.add(item["Id"])
                continue
            
            # Check album field
            album = (item.get("Album") or "").lower()
            if any(excluded in album for excluded in EXCLUDED_COLLECTIONS):
                excluded_ids.add(item["Id"])
                continue
            
            # Check file name for lullaby/sleeper
            name = (item.get("Name") or "").lower()
            if "lullaby" in name or "sleeper" in name:
                excluded_ids.add(item["Id"])
                continue
        
        # Update cache
        self._cache = excluded_ids
        self._cache_time = time.time()
        
        logger.info(f"[excluded_items] Cached {len(excluded_ids)} excluded items")
        return excluded_ids
    
    def clear_cache(self):
        """Manually clear the cache."""
        self._cache = None
        self._cache_time = None
        logger.info("[excluded_items] Cache cleared")