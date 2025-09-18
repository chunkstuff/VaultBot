# core/bot/cogs/makemeworseplus/session_incrementor.py

import json
import asyncio
from typing import Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from utils.logger_factory import setup_logger
from core.events.playlist_events import PlaylistCompleteEvent
from .playlist_tracking_db_helpers import (
    find_candidate_playlists_by_first_item,
    get_playlist_track_at_index,
    upsert_playlist_session,
    record_file_completion,
    mark_session_complete,
    get_track_runtime,
    get_playlist_length,
    get_playlist_info,
    calculate_session_listen_time,
    get_order_index_for_item,
)
from .session_state import SessionState
from .session_event_dispatcher import SessionEventDispatcher

logger = setup_logger(__name__)

# Heuristic thresholds
TICKS_PER_SECOND = 10_000_000
FINISH_THRESHOLD_SECS = 60
ORDER_ADVANCE_MIN_SECS = 10  # Minimum absolute threshold (for very short tracks)
ORDER_ADVANCE_PERCENTAGE = 0.67  # Must listen to at least 67% (2/3) of track to count as completion
COMPLETION_PERCENTAGE = 0.90  # 90% through track counts as completion for final track
MAX_EVENT_DELAY_SECONDS = 300  # Maximum delay for event emission (5 minutes)
SEED_TIME_GUARD_SECONDS = 30

class PlaylistIncrementProcessor:
    """Handles processing of individual playlist increments with defensive timestamp validation"""
    
    def __init__(self, vault_db, event_dispatcher: SessionEventDispatcher):
        self.vault_db = vault_db
        self.event_dispatcher = event_dispatcher
        self._background_tasks: set = set()

    def _schedule_background_task(self, coro):
        """Schedule a background task and track it for cleanup"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def cleanup_background_tasks(self):
        """Cancel all pending background tasks (call during shutdown)"""
        if self._background_tasks:
            logger.info(f"[PlaylistTracker] Cancelling {len(self._background_tasks)} background tasks...")
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()
            
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
            logger.info("[PlaylistTracker] Background tasks cleaned up")

    async def process_increment(self, discord_id: str, jellyfin_user_id: str, 
                              item_id: str, secs: int, 
                              current_state: Optional[SessionState]) -> Optional[SessionState]:
        """Process a single increment with defensive timestamp validation"""
        now = datetime.now(ZoneInfo("Europe/London"))
        
        if not current_state:
            return await self._handle_session_seed(discord_id, jellyfin_user_id, item_id, secs, now)
        
        return await self._handle_existing_session(discord_id, jellyfin_user_id, item_id, secs, now, current_state)

    async def _handle_session_seed(self, discord_id: str, jellyfin_user_id: str, 
                                 item_id: str, initial_secs: int, now: datetime) -> Optional[SessionState]:
        """Handle seeding a new session"""
        candidates = await find_candidate_playlists_by_first_item(
            self.vault_db, discord_id, item_id
        )
        if not candidates:
            return None
            
        chosen = candidates[0]
        user_playlist_id = int(chosen["user_playlist_id"])
        total_runtime = await self._get_playlist_total_runtime(user_playlist_id)
        jf_playlist_id = await self._get_jellyfin_playlist_id(user_playlist_id)
        auto_confirm = (len(candidates) == 1)

        # Apply seeding guard: only credit initial time if within reasonable startup window
        credited_initial_time = initial_secs if initial_secs <= SEED_TIME_GUARD_SECONDS else 0
        
        if credited_initial_time != initial_secs:
            logger.debug(
                f"[PlaylistTracker] {discord_id} seed guard applied: detected at {initial_secs}s "
                f"(> {SEED_TIME_GUARD_SECONDS}s guard), starting from 0s instead"
            )

        state = SessionState(
            session_id=None,
            user_playlist_id=user_playlist_id,
            jf_playlist_id=jf_playlist_id,
            current_index=0,
            is_confirmed=auto_confirm,
            current_item_id=item_id,
            seconds_accum=credited_initial_time,
            playlist_length=None,
            playlist_total_runtime=total_runtime,
            second_expected=chosen.get("second"),
            jellyfin_user_id=jellyfin_user_id,
            track_started_at=now,  # Start tracking time for this track
        )

        # Auto-confirm and persist if only one candidate
        if auto_confirm:
            state.session_id = await upsert_playlist_session(
                self.vault_db, discord_id, state.user_playlist_id,
                state.jf_playlist_id, state.current_index, state.is_confirmed
            )
            logger.info(
                f"[PlaylistSessionTracker] Auto-confirmed unique seed for {discord_id} "
                f"(playlist {state.user_playlist_id} @ index 0) with {credited_initial_time}s initial time"
            )

        await self.event_dispatcher.emit_playlist_start(discord_id, state, item_id)
        logger.info(
            f"[PlaylistSessionTracker] Seeded session for {discord_id} with playlist {state.user_playlist_id} "
            f"starting with {credited_initial_time}s accumulated time (detected at {initial_secs}s)"
        )
        
        return state

    async def _handle_existing_session(self, discord_id: str, jellyfin_user_id: str,
                                     item_id: str, secs: int, now: datetime,
                                     state: SessionState) -> Optional[SessionState]:
        """Handle increment for existing session"""
        
        # Check if user switched away from tracked playlist (only applies once confirmed)
        if state.is_confirmed:
            playlist_items = await self._get_all_playlist_items(state.user_playlist_id)
            if item_id not in playlist_items:
                await self.event_dispatcher.emit_switch_away(discord_id, state, item_id)
                logger.info(f"[PlaylistSessionTracker] {discord_id} switched away from playlist {state.user_playlist_id}, ending session")
                return None

        # Same item - just accumulate time
        if state.current_item_id == item_id:
            return await self._handle_same_item_increment(discord_id, state, secs)
        
        # Different item - check if advancing or jumping
        return await self._handle_item_change(discord_id, jellyfin_user_id, item_id, secs, now, state)

    async def _handle_same_item_increment(self, discord_id: str, state: SessionState, 
                                        secs: int) -> SessionState:
        """Handle time accumulation on the same item"""
        state.seconds_accum += secs
        
        # Get track count if we don't have it yet
        if not state.playlist_length:
            state.playlist_length = await get_playlist_length(self.vault_db, state.user_playlist_id)
        
        # Check if we've completed the final track
        if (state.is_confirmed and state.playlist_length and 
            state.current_index >= (state.playlist_length - 1)):
            
            completion_threshold = await self._calculate_completion_threshold(state.current_item_id)
            
            if state.seconds_accum >= completion_threshold:
                logger.debug(
                    f"[PlaylistTracker] {discord_id} reached completion threshold on final track "
                    f"({state.seconds_accum:.1f}s >= {completion_threshold:.1f}s)"
                )
                await self._finalize_if_complete(discord_id, state, state.playlist_length)
                return None  # Session completed and cleaned up
        
        return state

    async def _handle_item_change(self, discord_id: str, jellyfin_user_id: str,
                                item_id: str, secs: int, now: datetime, 
                                state: SessionState) -> Optional[SessionState]:
        """Handle when the current item changes"""
        next_idx = state.current_index + 1
        expected_next = await get_playlist_track_at_index(
            self.vault_db, state.user_playlist_id, next_idx
        )

        if expected_next and expected_next == item_id:
            return await self._handle_sequential_advance(discord_id, item_id, now, state, next_idx)
        else:
            return await self._handle_non_sequential_jump(discord_id, jellyfin_user_id, item_id, secs, now, state)

    async def _handle_sequential_advance(self, discord_id: str, item_id: str,
                                       now: datetime, state: SessionState, next_idx: int) -> SessionState:
        """
        Handle advancing to the next expected track.
        Uses defensive timestamp validation to prevent false skip detection.
        """
        # Calculate dynamic threshold using helper method
        advance_threshold = await self._calculate_advance_threshold(state.current_item_id)
        
        # Primary detection: check accumulated seconds
        if state.seconds_accum >= advance_threshold:
            # Normal completion path
            is_completion = True
            logger.debug(
                f"[PlaylistTracker] {discord_id} completed track {state.current_index} "
                f"({state.seconds_accum:.1f}s >= {advance_threshold:.1f}s threshold)"
            )
        else:
            # DETECTED SKIP - double-check with timestamp
            time_spent = (now - state.track_started_at).total_seconds() if state.track_started_at else 0
            
            if time_spent >= advance_threshold:
                # Override: timestamp says they actually did listen enough
                is_completion = True
                logger.info(
                    f"[DefensiveCheck] {discord_id} override skip -> completion based on timestamp "
                    f"(accum: {state.seconds_accum:.1f}s, actual: {time_spent:.1f}s, threshold: {advance_threshold:.1f}s)"
                )
            else:
                # Confirm: it really was a skip
                is_completion = False
                logger.debug(
                    f"[PlaylistTracker] {discord_id} skipped track {state.current_index} "
                    f"(accum: {state.seconds_accum:.1f}s, actual: {time_spent:.1f}s < {advance_threshold:.1f}s threshold)"
                )
        
        await self._process_track_completion(discord_id, state, next_idx, item_id, is_completion, now)
        return state

    async def _handle_non_sequential_jump(self, discord_id: str, jellyfin_user_id: str,
                                        item_id: str, secs: int, now: datetime,
                                        state: SessionState) -> Optional[SessionState]:
        """Handle jumping to a non-sequential track"""
        if state.is_confirmed or state.current_index > 0:
            new_idx = await get_order_index_for_item(self.vault_db, state.user_playlist_id, item_id)
            
            if new_idx is None:
                # Outside playlist - switch away
                await self.event_dispatcher.emit_switch_away(discord_id, state, item_id)
                logger.info(f"[PlaylistSessionTracker] {discord_id} jumped to item outside playlist, ending session")
                return None
            
            # Jump within playlist - apply time guard for the new track
            credited_jump_time = secs if secs <= SEED_TIME_GUARD_SECONDS else 0
            
            if credited_jump_time != secs:
                logger.debug(
                    f"[PlaylistTracker] {discord_id} jump guard applied: detected at {secs}s "
                    f"(> {SEED_TIME_GUARD_SECONDS}s guard), starting from 0s instead"
                )
            
            await self._process_playlist_jump(discord_id, state, new_idx, item_id, credited_jump_time, now)
            return state
        else:
            # Unconfirmed first track jumping to unexpected - reset
            logger.info(f"[PlaylistTracker] {discord_id} jumped to unexpected track, resetting session")
            return None

    async def _process_track_completion(self, discord_id: str, state: SessionState,
                                      next_idx: int, item_id: str, is_completion: bool,
                                      now: datetime):
        """Process track advancement with proper time recording"""
        # Confirm session if needed
        was_unconfirmed_first = (state.current_index == 0 and not state.is_confirmed)
        state.is_confirmed = state.is_confirmed or was_unconfirmed_first

        if not state.playlist_length:
            state.playlist_length = await get_playlist_length(self.vault_db, state.user_playlist_id)

        # Ensure session exists
        state.session_id = await upsert_playlist_session(
            self.vault_db, discord_id, state.user_playlist_id,
            state.jf_playlist_id, state.current_index, state.is_confirmed
        )

        # Calculate time to record
        if is_completion:
            # Always record full track runtime for completions
            track_runtime = await get_track_runtime(self.vault_db, state.current_item_id)
            time_to_record = track_runtime
            logger.debug(f"[PlaylistTracker] {discord_id} completed track {state.current_index} - recording full track time ({track_runtime:.1f}s)")
        else:
            # For skips, record actual time spent (either accumulated or timestamp-based)
            if state.track_started_at:
                time_spent = (now - state.track_started_at).total_seconds()
                time_to_record = max(state.seconds_accum, time_spent)  # Use whichever is higher
            else:
                time_to_record = state.seconds_accum
            time_to_record = max(0, time_to_record)  # Don't record negative time
            logger.debug(f"[PlaylistTracker] {discord_id} skipped track {state.current_index} - recording actual time ({time_to_record:.1f}s)")

        # Record time on previous track
        if time_to_record > 0:
            await record_file_completion(
                self.vault_db, state.session_id,
                state.current_item_id, state.current_index, time_to_record
            )

        # Store previous state for event
        prev_time = time_to_record
        prev_item = state.current_item_id
        prev_index = state.current_index

        # Update state for new track
        state.current_index = next_idx
        state.current_item_id = item_id
        state.seconds_accum = 0.0  # Reset for new track
        state.track_started_at = now  # Start tracking time for new track

        # Update DB
        await upsert_playlist_session(
            self.vault_db, discord_id, state.user_playlist_id,
            state.jf_playlist_id, state.current_index, state.is_confirmed
        )

        if is_completion:
            await self.event_dispatcher.emit_track_advance(
                discord_id, state, prev_index, prev_item, prev_time, item_id
            )
            logger.info(f"[PlaylistSessionTracker] {discord_id} advanced to track {next_idx}")
        else:
            await self.event_dispatcher.emit_track_jump(
                discord_id, state, prev_index, prev_item, prev_time, item_id
            )
            logger.info(f"[PlaylistSessionTracker] {discord_id} skipped to track {next_idx}")

    async def _process_playlist_jump(self, discord_id: str, state: SessionState,
                                   new_idx: int, item_id: str, new_track_secs: float, now: datetime):
        """Process jumping within the playlist"""
        if not state.playlist_length:
            state.playlist_length = await get_playlist_length(self.vault_db, state.user_playlist_id)

        # Update session
        state.session_id = await upsert_playlist_session(
            self.vault_db, discord_id, state.user_playlist_id,
            state.jf_playlist_id, new_idx, state.is_confirmed
        )

        # Store previous state for event
        prev_index = state.current_index
        prev_item = state.current_item_id
        prev_secs = state.seconds_accum

        # Update state for jumped track
        state.current_index = new_idx
        state.current_item_id = item_id
        state.seconds_accum = new_track_secs  # Start with credited time
        state.track_started_at = now  # Start tracking time for new track

        await self.event_dispatcher.emit_track_advance(
            discord_id, state, prev_index, prev_item, prev_secs, item_id
        )

        logger.info(f"[PlaylistSessionTracker] {discord_id} jumped within playlist to index {new_idx}")

    async def _finalize_if_complete(self, discord_id: str, state: SessionState, 
                                  total_tracks: int) -> bool:
        """Check if user completed the playlist"""
        if not state.is_confirmed:
            return False
        
        # Use dynamic completion threshold
        completion_threshold = await self._calculate_completion_threshold(state.current_item_id)
        
        if (state.current_index >= (total_tracks - 1) and 
            state.seconds_accum >= completion_threshold):
            
            if state.session_id:
                # For final track completion, always record full track time
                track_runtime = await get_track_runtime(self.vault_db, state.current_item_id)
                time_to_record = track_runtime
                delay_seconds = min(max(0, track_runtime - state.seconds_accum), MAX_EVENT_DELAY_SECONDS) if state.seconds_accum >= completion_threshold else 0
                should_delay_completion = state.seconds_accum >= completion_threshold
                
                await record_file_completion(
                    self.vault_db, state.session_id, state.current_item_id, 
                    state.current_index, time_to_record
                )
                await mark_session_complete(self.vault_db, state.session_id)

                # Wait for the track to "finish" ONLY if we're crediting extra time (non-blocking)
                if should_delay_completion and delay_seconds > 0:
                    logger.debug(f"[PlaylistTracker] Scheduling delayed playlist completion for {discord_id} in {delay_seconds:.1f}s")
                    # Create background task for delayed playlist completion - track it for cleanup
                    self._schedule_background_task(self._emit_delayed_playlist_completion(
                        discord_id, state, total_tracks, delay_seconds
                    ))
                else:
                    # Immediate playlist completion event
                    await self._emit_completion_event(discord_id, state, total_tracks)
                
                completion_type = "with time credit (delayed)" if should_delay_completion else "standard (immediate)"
                logger.info(
                    f"[PlaylistSessionTracker] {discord_id} completed playlist {state.user_playlist_id} "
                    f"({completion_type}) after {state.seconds_accum:.1f}s on final track "
                    f"(threshold: {completion_threshold:.1f}s) - recorded {time_to_record:.1f}s"
                )
                return True
        return False

    async def _emit_completion_event(self, discord_id: str, state: SessionState, total_tracks: int):
        """Emit playlist completion event"""
        if not self.event_dispatcher.dispatch:
            return
            
        try:
            playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.event_dispatcher.link_map.get_discord_info(state.jellyfin_user_id)
            jf_playlist_id = await self._get_jellyfin_playlist_id(state.user_playlist_id)
            total_listen_time = await calculate_session_listen_time(self.vault_db, state.session_id)
            
            complete_event = PlaylistCompleteEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=state.jellyfin_user_id,
                playlist_id=jf_playlist_id,
                playlist_session_id=state.session_id,
                user_playlist_id=state.user_playlist_id,
                playlist_name=playlist_info.get("playlist_name", "Unknown"),
                total_tracks=total_tracks,
                completed_tracks=state.current_index + 1,
                completion_time=datetime.now(ZoneInfo("Europe/London")),
                listen_duration=total_listen_time
            )
            
            self.event_dispatcher.dispatch('playlist_complete', complete_event)
        except Exception as e:
            logger.error(f'[PlaylistTracker] completion event emit failed: {e}')

    async def _emit_delayed_playlist_completion(self, discord_id: str, state: SessionState,
                                              total_tracks: int, delay_seconds: float):
        """Emit playlist completion event after a delay (runs in background)"""
        try:
            await asyncio.sleep(delay_seconds)
            await self._emit_completion_event(discord_id, state, total_tracks)
            logger.info(f"[PlaylistSessionTracker] {discord_id} delayed playlist completion event emitted (after {delay_seconds:.1f}s)")
        except Exception as e:
            logger.error(f"[PlaylistTracker] Failed to emit delayed playlist completion for {discord_id}: {e}")

    async def _calculate_completion_threshold(self, item_id: str, percentage: float = COMPLETION_PERCENTAGE) -> float:
        """Calculate dynamic completion threshold based on track runtime"""
        track_runtime = await get_track_runtime(self.vault_db, item_id)
        return track_runtime * percentage

    async def _calculate_advance_threshold(self, item_id: str) -> float:
        """
        Calculate dynamic advance threshold for track completion.
        When user advances to next track, we check if they listened to enough of the previous track
        to count it as "completed" vs "skipped". Requires 2/3 of track OR 10 seconds minimum.
        """
        track_runtime = await get_track_runtime(self.vault_db, item_id)
        percentage_threshold = track_runtime * ORDER_ADVANCE_PERCENTAGE
        return max(ORDER_ADVANCE_MIN_SECS, percentage_threshold)

    async def _get_playlist_total_runtime(self, user_playlist_id: int) -> float:
        """Get total runtime of all tracks in playlist (in seconds)"""
        rows = await self.vault_db.query("""
            SELECT metadata_json 
            FROM playlist_items pi
            JOIN items i ON pi.item_id = i.id
            WHERE pi.user_playlist_id = ?
        """, (user_playlist_id,))
        
        total_ticks = 0
        for row in rows:
            if row["metadata_json"]:
                try:
                    metadata = json.loads(row["metadata_json"])
                    runtime_ticks = metadata.get("RunTimeTicks", 0)
                    total_ticks += runtime_ticks
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in metadata for playlist {user_playlist_id}")
                    continue
        
        return total_ticks / TICKS_PER_SECOND

    async def _get_jellyfin_playlist_id(self, user_playlist_id: int) -> Optional[str]:
        """Get Jellyfin playlist ID from user playlist"""
        rows = await self.vault_db.query("""
            SELECT DISTINCT pi.jf_playlist_id 
            FROM playlist_items pi 
            WHERE pi.user_playlist_id = ? 
            AND pi.jf_playlist_id IS NOT NULL
            LIMIT 1
        """, (user_playlist_id,))
        
        return rows[0]["jf_playlist_id"] if rows else None

    async def _get_all_playlist_items(self, user_playlist_id: int) -> set[str]:
        """Get all item IDs for a playlist"""
        rows = await self.vault_db.query("""
            SELECT item_id FROM playlist_items 
            WHERE user_playlist_id = ?
        """, (user_playlist_id,))
        return {row["item_id"] for row in rows}