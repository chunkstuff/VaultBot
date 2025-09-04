import traceback
import asyncio
from typing import Dict, Any, Optional
from utils.logger_factory import setup_logger
from .session_state import SessionState
from .session_event_dispatcher import SessionEventDispatcher
from .session_incrementor import PlaylistIncrementProcessor, TICKS_PER_SECOND
from .session_abandon import SessionAbandonmentTracker
logger = setup_logger(__name__)


class PlaylistSessionTracker:
    """Main playlist session tracker - now much cleaner!"""
    
    def __init__(self, vault_db, link_map, dispatch=None):
        self.vault_db = vault_db
        self.link_map = link_map
        self.dispatch = dispatch
        
        # State management
        self._states: Dict[str, SessionState] = {}
        
        # Component classes
        self.event_dispatcher = SessionEventDispatcher(dispatch, link_map, vault_db)
        self.increment_processor = PlaylistIncrementProcessor(vault_db, self.event_dispatcher)
        self.abandonment_tracker = SessionAbandonmentTracker(self.event_dispatcher, vault_db)



    async def process_buffer_deltas(self, buffer_deltas: list[tuple[str, str, int]]):
        """Process session deltas from BufferManager"""
        try:
            for jf_user_id, item_id, secs in buffer_deltas:
                info = await self.link_map.get_discord_info(jf_user_id)
                if not info:
                    continue
                    
                discord_id = info[0]
                current_state = self._states.get(discord_id)
                
                # Process the increment
                new_state = await self.increment_processor.process_increment(
                    discord_id, jf_user_id, item_id, secs, current_state
                )
                
                # Update or remove state
                if new_state:
                    self._states[discord_id] = new_state
                else:
                    self._states.pop(discord_id, None)
                    
        except Exception as e:
            logger.error(f'[PlaylistTracker] Unexpected error: {e}')
            logger.error(traceback.format_exc())

    async def check_for_abandoned_sessions(self, current_streaming_discord_ids: set[str]):
        """Check for and handle abandoned sessions"""
        currently_tracked = set(self._states.keys())
        
        abandoned_users = await self.abandonment_tracker.check_for_abandoned_sessions(
            current_streaming_discord_ids, currently_tracked
        )
        
        # Process each abandoned user
        for discord_id in abandoned_users:
            state = self._states.get(discord_id)
            if state:
                processed = await self.abandonment_tracker.handle_session_abandonment(discord_id, state)
                if processed:
                    self._states.pop(discord_id, None)

    async def seed_from_existing_session_row(self, session_row: dict, jf_user_id: str,
                                           now_item_id: str, position_ticks: int,
                                           playlist_length: int) -> bool:
        """Reattach an existing DB session in memory"""
        discord_id = str(session_row["discord_id"])
        if discord_id in self._states:
            return False  # already tracking this user

        state = SessionState(
            session_id=int(session_row["session_id"]),
            user_playlist_id=int(session_row["user_playlist_id"]),
            jf_playlist_id=session_row.get("jf_playlist_id") or "",
            current_index=int(session_row["current_index"]),
            is_confirmed=True,  # exact match (playlist+index)
            current_item_id=now_item_id,
            seconds_accum=float(position_ticks or 0) / TICKS_PER_SECOND,
            playlist_length=int(playlist_length),
            playlist_total_runtime=0,
            second_expected=None,
            jellyfin_user_id=jf_user_id,
        )
        
        self._states[discord_id] = state
        
        logger.info(
            f"[PlaylistSessionTracker] Reattached session {session_row['session_id']} "
            f"(playlist {session_row['user_playlist_id']} @ index {session_row['current_index']})"
        )
        return True

    def get_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Get current active sessions for monitoring (backward compatibility)"""
        return {
            discord_id: state.to_dict() 
            for discord_id, state in self._states.items()
        }

    def get_active_session_states(self) -> Dict[str, SessionState]:
        """Get current active session states"""
        return self._states.copy()

    def get_abandonment_debug_info(self) -> Dict[str, Any]:
        """Get debug info about abandonment tracking"""
        base_info = self.abandonment_tracker.get_debug_info()
        base_info.update({
            "tracked_users": list(self._states.keys()),
            "total_tracked": len(self._states)
        })
        return base_info

    # Legacy methods for backward compatibility
    async def finalize_if_complete(self, discord_id: str, total_tracks: int) -> bool:
        """Legacy method - now handled internally by increment processor"""
        state = self._states.get(discord_id)
        if not state:
            return False
        
        completed = await self.increment_processor._finalize_if_complete(discord_id, state, total_tracks)
        if completed:
            self._states.pop(discord_id, None)
        return completed

    async def get_playlist_total_runtime(self, user_playlist_id: int) -> float:
        """Legacy method - delegate to increment processor"""
        return await self.increment_processor._get_playlist_total_runtime(user_playlist_id)

    async def _get_jellyfin_playlist_id(self, user_playlist_id: int) -> Optional[str]:
        """Legacy method - delegate to increment processor"""
        return await self.increment_processor._get_jellyfin_playlist_id(user_playlist_id)

    async def _get_all_playlist_items(self, user_playlist_id: int) -> set[str]:
        """Legacy method - delegate to increment processor"""
        return await self.increment_processor._get_all_playlist_items(user_playlist_id)