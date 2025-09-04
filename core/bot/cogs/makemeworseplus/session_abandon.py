from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils.logger_factory import setup_logger
from .session_event_dispatcher import SessionEventDispatcher
from .session_state import SessionState
from .session_incrementor import COMPLETION_PERCENTAGE
from .playlist_tracking_db_helpers import get_track_runtime, record_file_completion, get_playlist_info, get_item_title

logger = setup_logger(__name__)

@dataclass
class SessionSnapshot:
    """Snapshot of session information for event emission later"""
    discord_id: str
    jellyfin_user_id: str
    user_playlist_id: int
    playlist_name: str
    current_index: int
    current_item_id: str
    current_item_title: Optional[str]
    seconds_accum: float
    session_id: Optional[int]
    last_seen: datetime

class SessionAbandonmentTracker:
    """Handles session abandonment detection and cleanup with lenient timing"""
    
    def __init__(self, event_dispatcher: SessionEventDispatcher, vault_db):
        self.event_dispatcher = event_dispatcher
        self.vault_db = vault_db
        
        # Timing thresholds (in check cycles)
        self.pause_threshold = 20      # 5 minutes at 15s intervals (20 * 15s = 300s = 5min)
        self.waiting_threshold = 60    # 15 minutes at 15s intervals (60 * 15s = 900s = 15min)
        self.abandonment_threshold = 240  # 60 minutes at 15s intervals (240 * 15s = 3600s = 60min)
        
        # Tracking state
        self._user_absence_count: Dict[str, int] = {}
        self._user_pause_time: Dict[str, datetime] = {}  # When user first went absent
        self._user_notified_paused: Dict[str, bool] = {}  # Whether we've sent "paused" notification
        self._user_notified_waiting: Dict[str, bool] = {}  # Whether we've sent "waiting" notification
        
        # NEW: Session snapshots for event emission
        self._session_snapshots: Dict[str, SessionSnapshot] = {}

    async def update_session_snapshots(self, current_states: Dict[str, SessionState]) -> None:
        """Update snapshots of current sessions for later event emission"""
        for discord_id, state in current_states.items():
            try:
                # Get additional info needed for events
                playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
                item_title = await get_item_title(self.vault_db, state.current_item_id)
                
                self._session_snapshots[discord_id] = SessionSnapshot(
                    discord_id=discord_id,
                    jellyfin_user_id=state.jellyfin_user_id,
                    user_playlist_id=state.user_playlist_id,
                    playlist_name=playlist_info.get("playlist_name", "Unknown"),
                    current_index=state.current_index,
                    current_item_id=state.current_item_id,
                    current_item_title=item_title,
                    seconds_accum=state.seconds_accum,
                    session_id=state.session_id,
                    last_seen=datetime.now(ZoneInfo("Europe/London"))
                )
                
            except Exception as e:
                logger.debug(f"[SessionAbandonmentTracker] Failed to update snapshot for {discord_id}: {e}")

    async def check_for_abandoned_sessions(self, current_streaming_discord_ids: set[str], 
                                         currently_tracked: set[str]) -> set[str]:
        """
        Check for abandoned sessions with lenient timing:
        - 0-5 min: Normal absence (no action)
        - 5-15 min: Paused state (emit pause event once)
        - 15-60 min: Waiting state (emit waiting event once)
        - 60+ min: Officially abandoned
        """
        abandoned_users = set()
        now = datetime.now(ZoneInfo("Europe/London"))
        
        # Reset all tracking for users who are currently streaming
        for discord_id in current_streaming_discord_ids:
            # Check if this user was absent and is now returning
            if discord_id in self._user_absence_count and self._user_notified_paused.get(discord_id, False):
                # User is resuming after being paused/waiting
                snapshot = self._session_snapshots.get(discord_id)
                await self._emit_session_resumed_event(discord_id, now, snapshot)
            
            self._reset_user_tracking(discord_id)
        
        # Process tracked users who aren't streaming
        absent_tracked_users = currently_tracked - current_streaming_discord_ids
        
        for discord_id in absent_tracked_users:
            # Increment absence count
            self._user_absence_count[discord_id] = self._user_absence_count.get(discord_id, 0) + 1
            absence_count = self._user_absence_count[discord_id]
            
            # Set pause time on first absence
            if absence_count == 1:
                self._user_pause_time[discord_id] = now
                logger.debug(f"[SessionAbandon] {discord_id} went absent at {now}")
            
            # Get snapshot for this user (if available)
            snapshot = self._session_snapshots.get(discord_id)
            
            # Check thresholds and emit events
            if absence_count == self.pause_threshold and not self._user_notified_paused.get(discord_id, False):
                # Just hit 5 minute mark - session is now "paused"
                await self._emit_session_paused_event(discord_id, now, snapshot)
                self._user_notified_paused[discord_id] = True
                
            elif absence_count == self.waiting_threshold and not self._user_notified_waiting.get(discord_id, False):
                # Hit 15 minute mark - session is now "waiting" 
                await self._emit_session_waiting_event(discord_id, now, snapshot)
                self._user_notified_waiting[discord_id] = True
                
            elif absence_count >= self.abandonment_threshold:
                # Official abandonment after 60 minutes total
                abandoned_users.add(discord_id)
                self._reset_user_tracking(discord_id)
        
        # Clean up tracking for users we're no longer monitoring
        self._cleanup_untracked_users(currently_tracked)
        
        return abandoned_users

    async def handle_session_abandonment(self, discord_id: str, state: SessionState) -> bool:
        """
        Handle when a user's session is officially abandoned after the full timeout.
        Returns True if abandonment was processed, False if session was unconfirmed.
        """
        # Only trigger abandonment for confirmed sessions
        if not state.is_confirmed:
            logger.info(f"[SessionAbandon] Unconfirmed session for {discord_id} abandoned, cleaning up silently")
            # Clean up snapshot for unconfirmed sessions
            self._session_snapshots.pop(discord_id, None)
            return False
        
        try:
            # Record any accumulated time on the current track before abandoning
            if state.session_id and state.seconds_accum > 0:
                # Check if they listened to 95%+ of the current track
                track_runtime = await get_track_runtime(self.vault_db, state.current_item_id)
                completion_threshold = track_runtime * COMPLETION_PERCENTAGE
                
                # Use full track time if 95%+ listened, otherwise use actual time
                time_to_record = track_runtime if state.seconds_accum >= completion_threshold else state.seconds_accum
                
                await record_file_completion(
                    self.vault_db, 
                    state.session_id, 
                    state.current_item_id, 
                    state.current_index, 
                    time_to_record
                )
                
                if time_to_record > state.seconds_accum:
                    logger.debug(
                        f"[SessionAbandon] {discord_id} abandonment: listened to 95%+ of track "
                        f"({state.seconds_accum:.1f}s/{track_runtime:.1f}s) - recorded full track time"
                    )
            
            # Use snapshot for event if available, otherwise use current state
            snapshot = self._session_snapshots.get(discord_id)
            if snapshot:
                await self._emit_abandonment_event_from_snapshot(snapshot)
                # Clean up the snapshot
                self._session_snapshots.pop(discord_id, None)
            else:
                # Fallback to current state (less ideal)
                await self.event_dispatcher.emit_session_abandoned(discord_id, state)
            
            # Calculate total absence time for logging
            pause_time = self._user_pause_time.get(discord_id)
            if pause_time:
                total_absence = datetime.now(ZoneInfo("Europe/London")) - pause_time
                logger.info(
                    f"[SessionAbandon] Session officially abandoned by {discord_id} on playlist "
                    f"{state.user_playlist_id} at track {state.current_index} "
                    f"(absent for {total_absence.total_seconds()/60:.1f} minutes)"
                )
            else:
                logger.info(
                    f"[SessionAbandon] Session abandoned by {discord_id} on playlist "
                    f"{state.user_playlist_id} at track {state.current_index}"
                )
            
            return True
        
        except Exception as e:
            logger.debug(f"[SessionAbandon] abandonment handling failed: {e}")
            # Clean up snapshot on error
            self._session_snapshots.pop(discord_id, None)
            return False

    async def _emit_abandonment_event_from_snapshot(self, snapshot: SessionSnapshot):
        """Emit session abandoned event using stored snapshot data"""
        if not self.event_dispatcher.dispatch:
            return
            
        try:
            from core.events.playlist_events import PlaylistSessionAbandonedEvent
            
            discord_info = await self.event_dispatcher.link_map.get_discord_info(snapshot.jellyfin_user_id)
            
            self.event_dispatcher.dispatch("playlist_session_abandoned", PlaylistSessionAbandonedEvent(
                discord_user_id=snapshot.discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=snapshot.jellyfin_user_id,
                user_playlist_id=snapshot.user_playlist_id,
                playlist_name=snapshot.playlist_name,
                last_index=snapshot.current_index,
                last_item_id=snapshot.current_item_id,
                seconds_on_last=snapshot.seconds_accum,
                abandoned_at=datetime.now(ZoneInfo("Europe/London")),
                last_item_title=snapshot.current_item_title,
                session_id=snapshot.session_id,
            ))
        except Exception as e:
            logger.debug(f"[SessionAbandonmentTracker] abandonment event emit failed: {e}")

    async def _emit_session_paused_event(self, discord_id: str, pause_time: datetime, snapshot: Optional[SessionSnapshot] = None):
        """Emit session paused event with snapshot if available"""
        try:
            logger.info(f"[SessionAbandon] Session paused for {discord_id} (5 minutes absent)")
            
            # Calculate minutes absent
            absence_start = self._user_pause_time.get(discord_id, pause_time)
            minutes_absent = (pause_time - absence_start).total_seconds() / 60
            
            if snapshot:
                await self._emit_session_paused_from_snapshot(snapshot, pause_time, minutes_absent)
            else:
                # Fallback to basic method (if you have one)
                logger.debug(f"[SessionAbandon] No snapshot available for pause event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionAbandon] pause event emit failed: {e}")

    async def _emit_session_waiting_event(self, discord_id: str, waiting_time: datetime, snapshot: Optional[SessionSnapshot] = None):
        """Emit session waiting event with snapshot if available"""
        try:
            logger.info(f"[SessionAbandon] Session waiting for {discord_id} (15 minutes absent, will abandon in 45 minutes)")
            
            # Calculate minutes absent
            absence_start = self._user_pause_time.get(discord_id, waiting_time)
            minutes_absent = (waiting_time - absence_start).total_seconds() / 60
            
            if snapshot:
                await self._emit_session_waiting_from_snapshot(snapshot, waiting_time, minutes_absent)
            else:
                # Fallback to basic method (if you have one)
                logger.debug(f"[SessionAbandon] No snapshot available for waiting event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionAbandon] waiting event emit failed: {e}")

    async def _emit_session_resumed_event(self, discord_id: str, resume_time: datetime, snapshot: Optional[SessionSnapshot] = None):
        """Emit session resumed event when user returns after being paused/waiting"""
        try:
            # Calculate how long they were away
            absence_start = self._user_pause_time.get(discord_id, resume_time)
            minutes_away = (resume_time - absence_start).total_seconds() / 60
            
            # Only emit if they were away for at least the pause threshold (5+ minutes)
            if minutes_away >= (self.pause_threshold * 15 / 60):
                logger.info(f"[SessionAbandon] Session resumed for {discord_id} (away for {minutes_away:.1f} minutes)")
                
                if snapshot:
                    await self._emit_session_resumed_from_snapshot(snapshot, resume_time, minutes_away)
                else:
                    # Fallback to basic method (if you have one)
                    logger.debug(f"[SessionAbandon] No snapshot available for resume event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionAbandon] resume event emit failed: {e}")

    async def _emit_session_paused_from_snapshot(self, snapshot: SessionSnapshot, pause_time: datetime, minutes_absent: float):
        """Emit session paused event using stored snapshot data"""
        if not self.event_dispatcher.dispatch:
            return
            
        try:
            from core.events.playlist_events import PlaylistSessionPausedEvent
            
            discord_info = await self.event_dispatcher.link_map.get_discord_info(snapshot.jellyfin_user_id)
            
            self.event_dispatcher.dispatch("playlist_session_paused", PlaylistSessionPausedEvent(
                discord_user_id=snapshot.discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=snapshot.jellyfin_user_id,
                user_playlist_id=snapshot.user_playlist_id,
                playlist_name=snapshot.playlist_name,
                current_index=snapshot.current_index,
                current_item_id=snapshot.current_item_id,
                paused_at=pause_time,
                minutes_absent=minutes_absent,
                current_item_title=snapshot.current_item_title,
                session_id=snapshot.session_id,
            ))
        except Exception as e:
            logger.debug(f"[SessionAbandonmentTracker] pause event emit failed: {e}")

    async def _emit_session_waiting_from_snapshot(self, snapshot: SessionSnapshot, waiting_time: datetime, minutes_absent: float):
        """Emit session waiting event using stored snapshot data"""
        if not self.event_dispatcher.dispatch:
            return
            
        try:
            from core.events.playlist_events import PlaylistSessionWaitingEvent
            
            discord_info = await self.event_dispatcher.link_map.get_discord_info(snapshot.jellyfin_user_id)
            
            self.event_dispatcher.dispatch("playlist_session_waiting", PlaylistSessionWaitingEvent(
                discord_user_id=snapshot.discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=snapshot.jellyfin_user_id,
                user_playlist_id=snapshot.user_playlist_id,
                playlist_name=snapshot.playlist_name,
                current_index=snapshot.current_index,
                current_item_id=snapshot.current_item_id,
                waiting_at=waiting_time,
                minutes_absent=minutes_absent,
                current_item_title=snapshot.current_item_title,
                session_id=snapshot.session_id,
            ))
        except Exception as e:
            logger.debug(f"[SessionAbandonmentTracker] waiting event emit failed: {e}")

    async def _emit_session_resumed_from_snapshot(self, snapshot: SessionSnapshot, resume_time: datetime, minutes_away: float):
        """Emit session resumed event using stored snapshot data"""
        if not self.event_dispatcher.dispatch:
            return
            
        try:
            from core.events.playlist_events import PlaylistSessionResumedEvent
            
            discord_info = await self.event_dispatcher.link_map.get_discord_info(snapshot.jellyfin_user_id)
            
            self.event_dispatcher.dispatch("playlist_session_resumed", PlaylistSessionResumedEvent(
                discord_user_id=snapshot.discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=snapshot.jellyfin_user_id,
                user_playlist_id=snapshot.user_playlist_id,
                playlist_name=snapshot.playlist_name,
                current_index=snapshot.current_index,
                current_item_id=snapshot.current_item_id,
                resumed_at=resume_time,
                minutes_away=minutes_away,
                current_item_title=snapshot.current_item_title,
                session_id=snapshot.session_id,
            ))
        except Exception as e:
            logger.debug(f"[SessionAbandonmentTracker] resume event emit failed: {e}")

    def _reset_user_tracking(self, discord_id: str):
        """Reset all tracking state for a user"""
        self._user_absence_count.pop(discord_id, None)
        self._user_pause_time.pop(discord_id, None)
        self._user_notified_paused.pop(discord_id, None)
        self._user_notified_waiting.pop(discord_id, None)
        # Don't clean up snapshots here - they're managed separately

    def _cleanup_untracked_users(self, currently_tracked: set[str]):
        """Clean up tracking for users we're no longer monitoring"""
        tracked_users = set(self._user_absence_count.keys())
        untracked_users = tracked_users - currently_tracked
        
        for discord_id in untracked_users:
            self._reset_user_tracking(discord_id)
        
        # Clean up old snapshots for users no longer tracked
        self._session_snapshots = {
            discord_id: snapshot 
            for discord_id, snapshot in self._session_snapshots.items() 
            if discord_id in currently_tracked
        }

    def get_debug_info(self) -> Dict[str, Any]:
        """Get debug info about abandonment tracking"""
        now = datetime.now(ZoneInfo("Europe/London"))
        
        debug_info = {
            "absence_counts": self._user_absence_count.copy(),
            "pause_threshold_minutes": self.pause_threshold * 15 / 60,  # Convert to minutes
            "waiting_threshold_minutes": self.waiting_threshold * 15 / 60,
            "abandonment_threshold_minutes": self.abandonment_threshold * 15 / 60,
            "users_in_pause": [],
            "users_in_waiting": [],
            "snapshots_stored": len(self._session_snapshots),
            "snapshot_users": list(self._session_snapshots.keys()),
        }
        
        # Add state information for each user
        for discord_id, absence_count in self._user_absence_count.items():
            pause_time = self._user_pause_time.get(discord_id)
            minutes_absent = 0
            if pause_time:
                minutes_absent = (now - pause_time).total_seconds() / 60
            
            user_info = {
                "discord_id": discord_id,
                "absence_count": absence_count,
                "minutes_absent": round(minutes_absent, 1),
            }
            
            if self.pause_threshold <= absence_count < self.waiting_threshold:
                debug_info["users_in_pause"].append(user_info)
            elif self.waiting_threshold <= absence_count < self.abandonment_threshold:
                debug_info["users_in_waiting"].append(user_info)
        
        return debug_info