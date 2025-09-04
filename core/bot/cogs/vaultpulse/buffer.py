# core/bot/cogs/vaultpulse/buffer.py

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils.logger_factory import setup_logger
from config.time_helpers import format_ticks
from ..makemeworseplus.playlist_tracking_db_helpers import get_track_runtime

logger = setup_logger(__name__)

MAX_JUMP_BACK = 5 * 10_000_000
INIT_BUFFER = 15 * 10_000_000
MAX_TICK_AGE = timedelta(hours=12)
TICKS_PER_SECOND = 10_000_000


@dataclass
class LastTick:
    ticks: int
    timestamp: float


class BufferManager:
    def __init__(self, vault_db=None):
        self._buffer = defaultdict(int)
        self._tz = ZoneInfo("Europe/London")
        self._tick_tracker: dict[tuple[str, str, datetime], int] = {}
        self._last_known_tick: dict[tuple[str, str], LastTick] = {}
        self._current_track: dict[str, str] = {}  # {user_id: item_id} - track currently playing
        self._consumed_ticks: dict[tuple[str, str, datetime], int] = {}
        self.vault_db = vault_db

    def consume_recent_deltas(self) -> list[tuple[str, str, int]]:
        """Returns only NEW listening time since last consumption"""
        deltas = []
        
        for (user_id, item_id, hour), total_ticks in self._buffer.items():
            current_item = self._current_track.get(user_id)
            
            if item_id == current_item:
                track_key = (user_id, item_id, hour)
                
                # Get how much was already consumed
                consumed = self._consumed_ticks.get(track_key, 0)
                
                # Calculate new ticks since last consumption
                new_ticks = total_ticks - consumed
                
                if new_ticks > 0:
                    new_seconds = new_ticks // TICKS_PER_SECOND
                    if new_seconds > 0:
                        deltas.append((user_id, item_id, new_seconds))
                        
                        # Mark these ticks as consumed
                        self._consumed_ticks[track_key] = total_ticks
        
        return deltas

    async def _get_track_runtime_ticks(self, item_id: str) -> int:
        """Get track runtime in ticks from database metadata"""
        if not self.vault_db:
            return 300 * TICKS_PER_SECOND  # Default 5 minutes
        
        runtime_seconds = await get_track_runtime(self.vault_db, item_id)
        return int(runtime_seconds * TICKS_PER_SECOND)

    def _handle_initial(
        self,
        user_item_key: tuple[str, str],
        track_key: tuple[str, str, datetime],
        ticks: int,
        now_ts: float,
        user_id: str,
        item_id: str,
    ):
        """
        Record first‐seen (user, item). If initial ticks ≤ INIT_BUFFER, seed buffer.
        """
        self._last_known_tick[user_item_key] = LastTick(ticks=ticks, timestamp=now_ts)

        if ticks <= INIT_BUFFER:
            self._tick_tracker[track_key] = ticks
            self._buffer[track_key] += ticks
            logger.debug(
                f"Initial playtime (≤ {format_ticks(INIT_BUFFER)}) "
                f"added for {user_id} on {item_id}: {format_ticks(ticks)}"
            )

        logger.debug(
            f"Initialized tick tracker for {user_id} on {item_id}: {format_ticks(ticks)}"
        )

    def _handle_subsequent(
        self,
        user_item_key: tuple[str, str],
        track_key: tuple[str, str, datetime],
        ticks: int,
        now_ts: float,
        user_id: str,
        item_id: str,
    ):
        """
        After first‐time logic: detect restarts, compute delta, update trackers.
        """
        last = self._last_known_tick[user_item_key]
        last_ticks = self._detect_restart(ticks, last.ticks, user_id, item_id)

        delta = self._safe_delta(ticks, last_ticks)
        if delta <= 0:
            return

        # Save updated last‐known
        self._last_known_tick[user_item_key] = LastTick(ticks=ticks, timestamp=now_ts)
        self._tick_tracker[track_key] = ticks
        self._buffer[track_key] += delta

        logger.debug(f"Delta for {user_id} on {item_id}: {format_ticks(delta)}")
        logger.debug(f"Last known tick for {user_item_key}: {format_ticks(last_ticks)}")

    async def _finalize_track_on_change(self, user_id: str, old_item_id: str):
        """When track changes, fill in the gap between last known position and track end"""
        user_item_key = (user_id, old_item_id)
        
        if user_item_key not in self._last_known_tick:
            return 0
        
        last_tick_data = self._last_known_tick[user_item_key]
        last_position_ticks = last_tick_data.ticks
        
        # Get actual track runtime
        track_runtime_ticks = await self._get_track_runtime_ticks(old_item_id)
        
        hour_key = self._current_hour()
        track_key = (user_id, old_item_id, hour_key)
        
        # Calculate the gap between last known position and track end
        gap_ticks = max(0, track_runtime_ticks - last_position_ticks)
        
        # Cap the gap at something reasonable (e.g., 30 seconds max)
        max_gap = 30 * TICKS_PER_SECOND
        gap_ticks = min(gap_ticks, max_gap)
        
        if gap_ticks > 0:
            self._buffer[track_key] += gap_ticks
            logger.debug(f"Filled gap: {gap_ticks/TICKS_PER_SECOND:.1f}s between last position ({last_position_ticks/TICKS_PER_SECOND:.1f}s) and track end ({track_runtime_ticks/TICKS_PER_SECOND:.1f}s)")
            return gap_ticks
        
        return 0

    def _detect_restart(self, current_ticks: int, last_ticks: int, user_id: str, item_id: str) -> int:
        """
        If current_ticks has jumped back more than MAX_JUMP_BACK, treat as a restart.
        Otherwise, return last_ticks unchanged.
        """
        if current_ticks < last_ticks - MAX_JUMP_BACK:
            logger.debug(f"Detected restart: resetting tick tracker for {user_id} on {item_id}")
            return 0
        return last_ticks

    def _prune_old_ticks(self):
        now = datetime.utcnow().timestamp()
        before = len(self._last_known_tick)
        self._last_known_tick = {
            key: last
            for key, last in self._last_known_tick.items()
            if now - last.timestamp < MAX_TICK_AGE.total_seconds()
        }
        after = len(self._last_known_tick)
        logger.debug(f"Pruned _last_known_tick: {before - after} expired entries")

    def _safe_delta(self, current: int, previous: int, max_allowed: int = 60 * 10_000_000) -> int:
        delta = current - previous
        return delta if 0 <= delta <= max_allowed else 0

    def _current_hour(self) -> datetime:
        now_uk = datetime.now(self._tz)
        return now_uk.replace(minute=0, second=0, microsecond=0)

   
    async def update(self, session: dict):
        user_id = session.get("UserId")
        item = session.get("NowPlayingItem", {})
        item_id = item.get("Id")
        if not user_id or not item_id:
            return

        old_item_id = self._current_track.get(user_id)
        if old_item_id and old_item_id != item_id:
            await self._finalize_track_on_change(user_id, old_item_id)

        # Track the current playing item for this user
        self._current_track[user_id] = item_id

        ticks = session.get("PlayState", {}).get("PositionTicks", 0)
        now_ts = datetime.utcnow().timestamp()
        hour_key = self._current_hour()

        track_key = (user_id, item_id, hour_key)
        user_item_key = (user_id, item_id)

        if user_item_key not in self._last_known_tick:
            self._handle_initial(user_item_key, track_key, ticks, now_ts, user_id, item_id)
        else:
            self._handle_subsequent(user_item_key, track_key, ticks, now_ts, user_id, item_id)

    def get_user_ids(self) -> set[str]:
        return {user_id for (user_id, _, _) in self._buffer}

    def get_item_ids(self) -> set[str]:
        return {item_id for (_, item_id, _) in self._buffer}

    def get_ticks_for_flush(self) -> dict[tuple[str, str, datetime], int]:
        return dict(self._buffer)

    def clear(self):
        self._buffer.clear()
        self._tick_tracker.clear()
        self._current_track.clear()
        self._consumed_ticks.clear()
        self._prune_old_ticks()

    def debug_dump(self) -> list[dict]:
        return [
            {"user": uid, "item": iid, "hour": hour.isoformat(), "ticks": ticks}
            for (uid, iid, hour), ticks in self._buffer.items()
        ]