from typing import Dict, Any

from utils.logger_factory import setup_logger
from .session_event_dispatcher import SessionEventDispatcher
from .session_state import SessionState
from .session_incrementor import COMPLETION_PERCENTAGE
from .playlist_tracking_db_helpers import get_track_runtime, record_file_completion

logger = setup_logger(__name__)

class SessionAbandonmentTracker:
    """Handles session abandonment detection and cleanup"""
    
    def __init__(self, event_dispatcher: SessionEventDispatcher, vault_db, timeout_checks: int = 4):
        self.event_dispatcher = event_dispatcher
        self.vault_db = vault_db
        self.timeout_checks = timeout_checks
        self._user_absence_count: Dict[str, int] = {}

    async def check_for_abandoned_sessions(self, current_streaming_discord_ids: set[str], 
                                         currently_tracked: set[str]) -> set[str]:
        """
        Check for abandoned sessions and return set of discord_ids that were abandoned.
        """
        abandoned_users = set()
        
        # Reset absence count for users who are currently streaming
        for discord_id in current_streaming_discord_ids:
            self._user_absence_count.pop(discord_id, None)
        
        # Increment absence count for tracked users who aren't streaming
        absent_tracked_users = currently_tracked - current_streaming_discord_ids
        
        for discord_id in absent_tracked_users:
            self._user_absence_count[discord_id] = self._user_absence_count.get(discord_id, 0) + 1
            
            # Only abandon after reaching the timeout threshold
            if self._user_absence_count[discord_id] >= self.timeout_checks:
                abandoned_users.add(discord_id)
                self._user_absence_count.pop(discord_id, None)
        
        # Clean up absence counts for users we're no longer tracking
        self._user_absence_count = {
            discord_id: count 
            for discord_id, count in self._user_absence_count.items() 
            if discord_id in currently_tracked
        }
        
        return abandoned_users

    async def handle_session_abandonment(self, discord_id: str, state: SessionState) -> bool:
        """
        Handle when a user completely stops streaming (session abandoned).
        Returns True if abandonment was processed, False if session was unconfirmed.
        """
        # Only trigger abandonment for confirmed sessions
        if not state.is_confirmed:
            logger.info(f"[PlaylistSessionTracker] Unconfirmed session for {discord_id} abandoned, cleaning up silently")
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
                        f"[PlaylistTracker] {discord_id} abandonment: listened to 95%+ of track "
                        f"({state.seconds_accum:.1f}s/{track_runtime:.1f}s) - recorded full track time"
                    )
            
            await self.event_dispatcher.emit_session_abandoned(discord_id, state)
            
            logger.info(
                f"[PlaylistSessionTracker] Session abandoned by {discord_id} on playlist "
                f"{state.user_playlist_id} at track {state.current_index}"
            )
            return True
        
        except Exception as e:
            logger.debug(f"[PlaylistSessionTracker] abandonment handling failed: {e}")
            return False

    def get_debug_info(self) -> Dict[str, Any]:
        """Get debug info about abandonment tracking"""
        return {
            "absence_counts": self._user_absence_count.copy(),
            "timeout_threshold": self.timeout_checks,
        }