# core/events/playlist_events.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

@dataclass
class PlaylistCreateEvent:
    """Emitted when a new playlist is created"""
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    playlist_name: str
    playlist_id: str  # Jellyfin playlist ID
    user_playlist_id: int  # Database row ID
    num_files: int
    collections: List[str]
    tags: List[str]
    created_at: datetime
    session_id: Optional[int] = None

@dataclass 
class PlaylistCompleteEvent:
    """Emitted when a user completes a playlist"""
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    playlist_id: str | None
    playlist_session_id: int
    user_playlist_id: int
    playlist_name: str
    total_tracks: int
    completed_tracks: int
    completion_time: datetime
    listen_duration: Optional[float] = None
    session_id: Optional[int] = None


@dataclass
class PlaylistStartEvent:
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    user_playlist_id: int
    playlist_name: str
    total_tracks: int
    current_index: int            # 0-based; display as +1
    current_item_id: str
    started_at: datetime
    current_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistTrackAdvanceEvent:
    discord_user_id: str
    discord_username: str
    user_playlist_id: int
    from_index: int               # 0-based; display as +1
    to_index: int                 # 0-based; display as +1
    from_item_id: str
    to_item_id: str
    seconds_on_from: float
    occurred_at: datetime
    total_tracks: int
    from_item_title: Optional[str] = None
    to_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistTrackJumpEvent:
    discord_user_id: str
    discord_username: str
    user_playlist_id: int
    from_index: int               # 0-based; display as +1
    to_index: int                 # 0-based; display as +1
    from_item_id: str
    to_item_id: str
    seconds_on_from: float
    occurred_at: datetime
    total_tracks: int
    from_item_title: Optional[str] = None
    to_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistSwitchAwayEvent:
    discord_user_id: str
    discord_username: str
    user_playlist_id: int
    playlist_name: str
    from_index: int               # 0-based; display as +1
    from_item_id: str
    seconds_on_from: float
    switched_to_item_id: Optional[str]
    occurred_at: datetime
    from_item_title: Optional[str] = None
    switched_to_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistSessionAbandonedEvent:
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    user_playlist_id: int
    playlist_name: str
    last_index: int
    last_item_id: str
    seconds_on_last: float 
    abandoned_at: datetime
    last_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistSessionPausedEvent:
    """Emitted when a user's session is paused (5 minutes absent)"""
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    user_playlist_id: int
    playlist_name: str
    current_index: int
    current_item_id: str
    paused_at: datetime
    minutes_absent: float
    current_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistSessionResumedEvent:
    """Emitted when a user resumes their session after being paused/waiting"""
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    user_playlist_id: int
    playlist_name: str
    current_index: int
    current_item_id: str
    resumed_at: datetime
    minutes_away: float
    current_item_title: Optional[str] = None
    session_id: Optional[int] = None

@dataclass
class PlaylistSessionWaitingEvent:
    """Emitted when a user's session is waiting for abandonment (15+ minutes absent)"""
    discord_user_id: str
    discord_username: str
    jellyfin_user_id: str
    user_playlist_id: int
    playlist_name: str
    current_index: int
    current_item_id: str
    waiting_at: datetime
    minutes_absent: float
    current_item_title: Optional[str] = None
    session_id: Optional[int] = None
