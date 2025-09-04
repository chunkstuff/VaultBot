from datetime import datetime
from zoneinfo import ZoneInfo
from utils.logger_factory import setup_logger
from core.events.playlist_events import (
    PlaylistStartEvent,
    PlaylistTrackAdvanceEvent,
    PlaylistSwitchAwayEvent,
    PlaylistTrackJumpEvent,
    PlaylistSessionAbandonedEvent
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
                from_item_title=prev_title,
                to_item_title=to_title,
                session_id=state.session_id,
            ))
        except Exception as e:
            logger.debug(f"[PlaylistTracker] skip event emit failed: {e}")

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