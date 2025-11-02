from datetime import datetime
from zoneinfo import ZoneInfo
from utils.logger_factory import setup_logger
from core.events.playlist_events import (
    PlaylistStartEvent,
    PlaylistTrackAdvanceEvent,
    PlaylistSwitchAwayEvent,
    PlaylistTrackJumpEvent,
    PlaylistSessionAbandonedEvent,
    PlaylistSessionPausedEvent,
    PlaylistSessionWaitingEvent,
    PlaylistSessionResumedEvent
)
from .playlist_tracking_db_helpers import (
    get_playlist_length,
    get_playlist_info,
    get_item_title
)
from .session_state import SessionState

logger = setup_logger(__name__)

class SessionEventDispatcher:
    """Handles dispatching of playlist events"""
    
    def __init__(self, dispatch_func, link_map, vault_db):
        self.dispatch = dispatch_func
        self.link_map = link_map
        self.vault_db = vault_db

    async def emit_playlist_start(self, discord_id: str, state: SessionState, item_id: str):
        """Emit playlist start event"""
        if not self.dispatch:
            return
            
        try:
            total_tracks = await get_playlist_length(self.vault_db, state.user_playlist_id) or 0
            info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            cur_title = await get_item_title(self.vault_db, item_id)

            self.dispatch("playlist_start", PlaylistStartEvent(
                discord_user_id=discord_id,
                discord_username=(discord_info[1] if discord_info else "Unknown"),
                jellyfin_user_id=state.jellyfin_user_id,
                user_playlist_id=state.user_playlist_id,
                playlist_name=info.get("playlist_name", "Unknown"),
                total_tracks=total_tracks,
                current_index=0,
                current_item_id=item_id,
                started_at=datetime.now(ZoneInfo("Europe/London")),
                current_item_title=cur_title,
                session_id=state.session_id,
            ))
        except Exception as e:
            logger.debug(f"[PlaylistTracker] start event emit failed: {e}")

    async def emit_track_advance(self, discord_id: str, state: SessionState, 
                               prev_index: int, prev_item: str, prev_secs: float, 
                               new_item: str):
        """Emit track advance event"""
        if not self.dispatch:
            return
            
        try:
            total_tracks = await get_playlist_length(self.vault_db, state.user_playlist_id) or 0
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            prev_title = await get_item_title(self.vault_db, prev_item)
            to_title = await get_item_title(self.vault_db, new_item)
            
            self.dispatch("playlist_track_advance", PlaylistTrackAdvanceEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                user_playlist_id=state.user_playlist_id,
                from_index=prev_index,
                to_index=state.current_index,
                from_item_id=prev_item,
                to_item_id=new_item,
                seconds_on_from=prev_secs,
                occurred_at=datetime.now(ZoneInfo("Europe/London")),
                total_tracks=total_tracks,
                from_item_title=prev_title,
                to_item_title=to_title,
                session_id=state.session_id,
            ))
        except Exception as e:
            logger.debug(f"[PlaylistTracker] advance event emit failed: {e}")

    async def emit_track_jump(self, discord_id: str, state: SessionState,
                            prev_index: int, prev_item: str, prev_secs: float,
                            new_item: str):
        """Emit track jump/skip event"""
        if not self.dispatch:
            return
            
        try:
            total_tracks = await get_playlist_length(self.vault_db, state.user_playlist_id) or 0
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            prev_title = await get_item_title(self.vault_db, prev_item)
            to_title = await get_item_title(self.vault_db, new_item)
            
            self.dispatch("playlist_track_jump", PlaylistTrackJumpEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                user_playlist_id=state.user_playlist_id,
                from_index=prev_index,
                to_index=state.current_index,
                from_item_id=prev_item,
                to_item_id=new_item,
                seconds_on_from=prev_secs,
                occurred_at=datetime.now(ZoneInfo("Europe/London")),
                total_tracks=total_tracks,
                from_item_title=prev_title,
                to_item_title=to_title,
                session_id=state.session_id,
            ))
        except Exception as e:
            logger.debug(f"[PlaylistTracker] jump event emit failed: {e}")

    async def emit_switch_away(self, discord_id: str, state: SessionState, new_item_id: str):
        """Emit switch away event"""
        if not self.dispatch:
            return
            
        try:
            playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            from_title = await get_item_title(self.vault_db, state.current_item_id)
            to_title = await get_item_title(self.vault_db, new_item_id) if new_item_id else None
            
            self.dispatch("playlist_switch_away", PlaylistSwitchAwayEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                user_playlist_id=state.user_playlist_id,
                playlist_name=playlist_info.get("playlist_name", "Unknown"),
                from_index=state.current_index,
                from_item_id=state.current_item_id,
                seconds_on_from=state.seconds_accum,
                switched_to_item_id=new_item_id,
                occurred_at=datetime.now(ZoneInfo("Europe/London")),
                from_item_title=from_title,
                switched_to_item_title=to_title,
                session_id=state.session_id,
            ))
        except Exception as e:
            logger.debug(f"[PlaylistTracker] switch away event emit failed: {e}")

    async def emit_session_abandoned(self, discord_id: str, state: SessionState):
        """Emit session abandoned event"""
        if not self.dispatch:
            return
            
        try:
            last_title = await get_item_title(self.vault_db, state.current_item_id)
            playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            
            self.dispatch("playlist_session_abandoned", PlaylistSessionAbandonedEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=state.jellyfin_user_id,
                user_playlist_id=state.user_playlist_id,
                playlist_name=playlist_info.get("playlist_name", "Unknown"),
                last_index=state.current_index,
                last_item_id=state.current_item_id,
                seconds_on_last=state.seconds_accum,
                abandoned_at=datetime.now(ZoneInfo("Europe/London")),
                last_item_title=last_title,
                session_id=state.session_id,
            ))
        except Exception as e:
            logger.debug(f"[PlaylistSessionTracker] abandonment event emit failed: {e}")
    
    async def emit_session_paused(self, discord_id: str, pause_time: datetime, minutes_absent: float):
        """Emit session paused event with full event object"""
        if not self.dispatch:
            return
            
        try:
            # Get the jellyfin user ID from the session state
            # We need to find the active session for this discord user
            # This is a simplified approach - you may need to pass session state directly
            
            # Try to get jellyfin user ID from link map
            jellyfin_user_id = None
            discord_info = None
            
            # For now, create a basic event with what we have
            # The session state would need to be passed to get complete info
            pause_event = PlaylistSessionPausedEvent(
                discord_user_id=discord_id,
                discord_username="Unknown User",  # Will be updated when we have session state access
                jellyfin_user_id="",
                user_playlist_id=0,
                playlist_name="Session",  # Generic name for now
                current_index=0,
                current_item_id="",
                paused_at=pause_time,
                minutes_absent=minutes_absent,
                current_item_title=None,
                session_id=None
            )
            
            self.dispatch("playlist_session_paused", pause_event)
            logger.debug(f"[SessionEventDispatcher] Emitted session_paused event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionEventDispatcher] pause event emit failed: {e}")

    async def emit_session_waiting(self, discord_id: str, waiting_time: datetime, minutes_absent: float):
        """Emit session waiting event with full event object"""
        if not self.dispatch:
            return
            
        try:
            # Same issue as above - need session state for complete info
            waiting_event = PlaylistSessionWaitingEvent(
                discord_user_id=discord_id,
                discord_username="Unknown User",  # Will be updated when we have session state access
                jellyfin_user_id="",
                user_playlist_id=0,
                playlist_name="Session",  # Generic name for now
                current_index=0,
                current_item_id="",
                waiting_at=waiting_time,
                minutes_absent=minutes_absent,
                current_item_title=None,
                session_id=None
            )
            
            self.dispatch("playlist_session_waiting", waiting_event)
            logger.debug(f"[SessionEventDispatcher] Emitted session_waiting event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionEventDispatcher] waiting event emit failed: {e}")

    async def emit_session_resumed_with_state(self, discord_id: str, state: 'SessionState', resume_time: datetime, minutes_away: float):
        """Emit session resumed event with complete session state information"""
        if not self.dispatch:
            return
            
        try:
            playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            current_title = await get_item_title(self.vault_db, state.current_item_id)
            
            resumed_event = PlaylistSessionResumedEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=state.jellyfin_user_id,
                user_playlist_id=state.user_playlist_id,
                playlist_name=playlist_info.get("playlist_name", "Unknown"),
                current_index=state.current_index,
                current_item_id=state.current_item_id,
                resumed_at=resume_time,
                minutes_away=minutes_away,
                current_item_title=current_title,
                session_id=state.session_id
            )
            
            self.dispatch("playlist_session_resumed", resumed_event)
            logger.debug(f"[SessionEventDispatcher] Emitted complete session_resumed event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionEventDispatcher] resume event emit failed: {e}")

    # ENHANCED VERSION - if you can pass session state to abandonment tracker
    async def emit_session_paused_with_state(self, discord_id: str, state: 'SessionState', pause_time: datetime, minutes_absent: float):
        """Emit session paused event with complete session state information"""
        if not self.dispatch:
            return
            
        try:
            playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            current_title = await get_item_title(self.vault_db, state.current_item_id)
            
            pause_event = PlaylistSessionPausedEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=state.jellyfin_user_id,
                user_playlist_id=state.user_playlist_id,
                playlist_name=playlist_info.get("playlist_name", "Unknown"),
                current_index=state.current_index,
                current_item_id=state.current_item_id,
                paused_at=pause_time,
                minutes_absent=minutes_absent,
                current_item_title=current_title,
                session_id=state.session_id
            )
            
            self.dispatch("playlist_session_paused", pause_event)
            logger.debug(f"[SessionEventDispatcher] Emitted complete session_paused event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionEventDispatcher] pause event emit failed: {e}")

    async def emit_session_waiting_with_state(self, discord_id: str, state: 'SessionState', waiting_time: datetime, minutes_absent: float):
        """Emit session waiting event with complete session state information"""
        if not self.dispatch:
            return
            
        try:
            playlist_info = await get_playlist_info(self.vault_db, state.user_playlist_id)
            discord_info = await self.link_map.get_discord_info(state.jellyfin_user_id)
            current_title = await get_item_title(self.vault_db, state.current_item_id)
            
            waiting_event = PlaylistSessionWaitingEvent(
                discord_user_id=discord_id,
                discord_username=discord_info[1] if discord_info else "Unknown",
                jellyfin_user_id=state.jellyfin_user_id,
                user_playlist_id=state.user_playlist_id,
                playlist_name=playlist_info.get("playlist_name", "Unknown"),
                current_index=state.current_index,
                current_item_id=state.current_item_id,
                waiting_at=waiting_time,
                minutes_absent=minutes_absent,
                current_item_title=current_title,
                session_id=state.session_id
            )
            
            self.dispatch("playlist_session_waiting", waiting_event)
            logger.debug(f"[SessionEventDispatcher] Emitted complete session_waiting event for {discord_id}")
            
        except Exception as e:
            logger.debug(f"[SessionEventDispatcher] waiting event emit failed: {e}")