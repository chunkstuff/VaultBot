import asyncio
import traceback
import logging
from discord.ext import tasks, commands
from datetime import datetime, timedelta

from utils.logger_factory import setup_logger
from .buffer import BufferManager
from .user import UserSync
from .item_sync import ItemSync
from .embed import EmbedBuilder
from ..makemeworseplus.playlist_tracking import PlaylistSessionTracker
from ..makemeworseplus.playlist_tracking_db_helpers import (
    find_recent_incomplete_session_for_user,
    get_playlist_item_id_at_index,
    get_playlist_length,
)

REATTACH_LOOKBACK_HOURS = 6

logger = setup_logger(__name__)

class VaultPulse(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = bot.client
        self.db = self.client.users.sessions.user_session_db
        self.buffer = BufferManager(vault_db=self.db)
        self.user_sync = UserSync(bot)
        self.item_sync = ItemSync(self.client)
        self.embed_builder = EmbedBuilder(self.bot, self.db)
        self.playlist_tracker = PlaylistSessionTracker(
            vault_db=self.db,
            link_map=self.bot.link_map,
            dispatch=bot.dispatch
        )
        self._tasks_started = False

        # guard so we only try reattach once per process boot
        self._reattach_has_run = False
        self._reattach_lock = asyncio.Lock()

    async def cog_load(self):
        # Called automatically when the cog is loaded in discord.py 2.x
        if not self._tasks_started:
            logger.info("[VaultPulse] Starting background tasks (cog_load).")
            self.check_sessions.start()
            self.flush_hourly_chunks.start()
            self.cleanup_hot_cache_task.start()
            self._tasks_started = True
            logger.info("[VaultPulse] Background tasks started.")

    async def cog_unload(self):
        logger.info("[VaultPulse] Cog unloading, cancelling tasks...")
        self.check_sessions.cancel()
        self.flush_hourly_chunks.cancel()
        self.cleanup_hot_cache_task.cancel()
        asyncio.create_task(self.flush())

    async def _maybe_reattach_for_jf_session(self, jf_session: dict) -> bool:
        jf_user_id = jf_session.get("UserId")
        now_item = jf_session.get("NowPlayingItem") or {}
        now_item_id = now_item.get("Id")
        if not jf_user_id or not now_item_id:
            return False

        # JF -> Discord
        discord_info = await self.bot.link_map.get_discord_info(jf_user_id)
        if not discord_info:
            return False
        discord_id, _ = discord_info

        # Already tracking this user? then nothing to do
        if self.playlist_tracker._states.get(discord_id):
            return False

        # --- fetch candidate session
        row = await find_recent_incomplete_session_for_user(self.db, discord_id, hours=REATTACH_LOOKBACK_HOURS)
        if not row:
            return False
        if isinstance(row, list):
            if not row: 
                return False
            row = row[0]

        # Normalize: if a list slipped through, take the first
        if isinstance(row, list):
            row = row[0] if row else None
        if not row:
            return False

        # Safe getters for dict/Row/tuple/int
        def _get(rowlike, key):
            try:
                if hasattr(rowlike, "keys"):
                    return rowlike[key]              # Row/dict
            except Exception:
                pass
            try:
                if isinstance(rowlike, (list, tuple)):
                    return rowlike[0]                # 1-col tuple/list
            except Exception:
                pass
            return None

        user_playlist_id = _get(row, "user_playlist_id")
        current_index    = _get(row, "current_index")
        session_id       = _get(row, "session_id")

        if user_playlist_id is None or current_index is None:
            # Helpful one-time diagnostic
            try:
                logger.warning(f"[Reattach] bad row shape: type={type(row).__name__} repr={repr(row)[:200]}")
            except Exception:
                logger.warning("[Reattach] bad row shape (unrepr)")
            return False

        try:
            user_playlist_id = int(user_playlist_id)
            current_index    = int(current_index)
        except Exception:
            logger.warning(f"[Reattach] non-int playlist/index: {user_playlist_id!r}, {current_index!r}")
            return False

        # Confirm we are on the same track at that index
        expected_item_id = await get_playlist_item_id_at_index(self.db, user_playlist_id, current_index)
        if not expected_item_id or expected_item_id != now_item_id:
            return False

        pos_ticks = (jf_session.get("PlayState") or {}).get("PositionTicks") or 0
        playlist_length = await get_playlist_length(self.db, user_playlist_id)

        attached = await self.playlist_tracker.seed_from_existing_session_row(
            session_row={
                "session_id": session_id if session_id is not None else -1,
                "discord_id": discord_id,
                "user_playlist_id": user_playlist_id,
                "jf_playlist_id": _get(row, "jf_playlist_id") or "",
                "current_index": current_index,
            },
            jf_user_id=jf_user_id,
            now_item_id=now_item_id,
            position_ticks=pos_ticks,
            playlist_length=playlist_length,
        )
        if attached:
            logger.info(f"[Reattach] Continued session {session_id} for Discord {discord_id}")
        return attached


    async def _reattach_once_with_sessions(self, sessions: list[dict] | None):
        """
        Run the reattach pass exactly once per process boot.
        Call this at the top of check_sessions after you've fetched /Sessions.
        """
        if self._reattach_has_run:
            return
        async with self._reattach_lock:
            if self._reattach_has_run:
                return
            # Mark as run immediately to ensure true "once per boot"
            self._reattach_has_run = True

            if not sessions:
                logger.info("[Reattach] Startup pass: no active Jellyfin sessions")
                return

            attached_any = False
            for s in sessions:
                try:
                    ok = await self._maybe_reattach_for_jf_session(s)
                    attached_any = attached_any or ok
                except Exception as e:
                    logger.warning(f"[Reattach] per-session attempt failed: {e}")
                    logger.error(traceback.format_exc())

            if attached_any:
                logger.info("[Reattach] Startup pass complete: at least one session continued")
            else:
                logger.info("[Reattach] Startup pass complete: nothing to continue")

    async def flush(self):
        if self.buffer.get_ticks_for_flush():
            try:
                if self.db._conn is None:
                    await self.db.connect()
                await self.db.upsert_users(await self.user_sync.prepare_user_rows(self.buffer, self.embed_builder._cached_users))
                await self.db.upsert_items(await self.item_sync.prepare_item_rows(self.buffer))
                await self.client.users.sessions.flush_buffer(self.buffer.get_ticks_for_flush())
                self.buffer.clear()
                logger.info("[VaultPulse] Buffer flushed successfully.")
            except Exception as e:
                logger.error(f"[VaultPulse] Buffer flush failed: {e}")

    @tasks.loop(hours=1)
    async def cleanup_hot_cache_task(self):
        """Clean up stale hot cache entries"""
        try:
            # Check if link_map is available (bot may still be starting up)
            if not hasattr(self.bot, 'link_map') or not self.bot.link_map:
                logger.debug("[VaultPulse] link_map not available yet; skipping hot cache cleanup.")
                return
                
            before_size = len(self.bot.link_map._hot_cache)
            self.bot.link_map.cleanup_stale_entries()
            after_size = len(self.bot.link_map._hot_cache)
            
            if before_size != after_size:
                logger.info(f"[VaultPulse] Hot cache cleanup completed: {before_size} -> {after_size} entries")
            else:
                logger.debug(f"[VaultPulse] Hot cache cleanup completed: {after_size} entries (no changes)")
                
        except Exception as e:
            logger.error(f"[VaultPulse] cleanup_hot_cache_task error: {e}")
            logger.error(traceback.format_exc())

    # ADD THIS BEFORE_LOOP:
    @cleanup_hot_cache_task.before_loop
    async def before_cleanup_hot_cache(self):
        try:
            logger.info("[VaultPulse] cleanup_hot_cache_task about to start looping.")
            # Start cleanup at the top of the hour
            now = datetime.utcnow()
            minutes_until_next_hour = 60 - now.minute
            seconds_until_next_hour = (minutes_until_next_hour * 60) - now.second
            await asyncio.sleep(seconds_until_next_hour)
        except RuntimeError as e:
            logger.info(f"[VaultPulse] Bot shutdown during before_loop: {e}")
            return

    @tasks.loop(seconds=15)
    async def check_sessions(self):
        try:
            sessions = await self.client.get_sessions()
            if not isinstance(sessions, list):
                return

            await self._reattach_once_with_sessions(sessions)
            active, streaming = self._get_active_and_streaming_sessions(sessions)

            # Get Discord IDs of currently streaming users
            current_streaming_discord_ids = set()
            for session in streaming:
                jf_user_id = session.get("UserId")
                if jf_user_id:
                    discord_info = await self.bot.link_map.get_discord_info(jf_user_id)
                    if discord_info:
                        current_streaming_discord_ids.add(discord_info[0])

            # Process streaming sessions
            for session in streaming:
                await self.buffer.update(session)

            # Process buffer deltas for playlist tracking
            buffer_deltas = self.buffer.consume_recent_deltas()
            if buffer_deltas:
                await self.playlist_tracker.process_buffer_deltas(buffer_deltas)

            # CRITICAL: Update session snapshots BEFORE checking for abandonment
            # This captures the current state information while we still have it
            current_states = self.playlist_tracker.get_active_session_states()
            await self.playlist_tracker.abandonment_tracker.update_session_snapshots(current_states)

            # Check for abandoned sessions AFTER capturing snapshots
            await self.playlist_tracker.check_for_abandoned_sessions(current_streaming_discord_ids)

            # Update embed
            embed = await self.embed_builder.build_status_embed(len(active), len(streaming), streaming)
            await self.embed_builder.update_or_send_embed(embed)

            # Optional: Debug playlist tracking state
            if logger.isEnabledFor(logging.DEBUG):
                debug_info = self.playlist_tracker.get_abandonment_debug_info()
                if debug_info["total_tracked"] > 0:
                    logger.debug(f"Playlist tracking: {debug_info}")
                logger.debug(self.buffer.debug_dump())
                logger.debug(f"Tick tracker: {self.buffer._tick_tracker}")
                logger.debug(f"Buffer: {self.buffer._buffer}")

        except Exception as e:
            logger.error(f"[VaultPulse] check_sessions error: {e}")
            logger.error(traceback.format_exc())

    @check_sessions.before_loop
    async def before_check_sessions(self):
        try:
            logger.info("[VaultPulse] check_sessions about to start looping.")
            # await self.bot.wait_until_ready()
            now = datetime.utcnow()
            await asyncio.sleep(15 - now.second % 15)
        except RuntimeError as e:
            logger.info(f"[VaultPulse] Bot shutdown during before_loop: {e}")
            return  # Exit cleanly

    @tasks.loop(hours=1)
    async def flush_hourly_chunks(self):
        logger.info("[VaultPulse] flush_hourly_chunks loop tick.")
        try:
            await self.flush()
        except Exception as e:
            logger.error(f"[VaultPulse] flush_hourly_chunks error: {e}")

    @flush_hourly_chunks.before_loop
    async def before_flush_hourly_chunks(self):
        try:
            logger.info("[VaultPulse] flush_hourly_chunks about to start looping.")
            # await self.bot.wait_until_ready()
            now = datetime.utcnow()
            seconds_until_next_hour = ((60 - now.minute) * 60) - now.second
            await asyncio.sleep(seconds_until_next_hour)
        except RuntimeError as e:
            logger.info(f"[VaultPulse] Bot shutdown during before_loop: {e}")
            return  # Exit cleanly

    def _get_active_and_streaming_sessions(self, sessions):
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=15)
        active = [
            s for s in sessions
            if (ts := s.get("LastActivityDate"))
            and datetime.fromisoformat(ts.rstrip("Z")) > cutoff
        ]
        streaming = [s for s in active if s.get("NowPlayingItem")]
        return active, streaming
