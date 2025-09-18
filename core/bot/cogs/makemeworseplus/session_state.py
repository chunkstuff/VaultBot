# core/bot/cogs/makemeworseplus/session_state.py

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime

@dataclass
class SessionState:
    """Represents the current state of a playlist session with defensive timestamp tracking"""
    session_id: Optional[int]
    user_playlist_id: int
    jf_playlist_id: Optional[str]
    current_index: int
    is_confirmed: bool
    current_item_id: str
    seconds_accum: float
    playlist_length: Optional[int]
    playlist_total_runtime: float
    second_expected: Optional[str]
    jellyfin_user_id: str
    track_started_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for backward compatibility"""
        return {
            "session_id": self.session_id,
            "user_playlist_id": self.user_playlist_id,
            "jf_playlist_id": self.jf_playlist_id,
            "current_index": self.current_index,
            "is_confirmed": self.is_confirmed,
            "current_item_id": self.current_item_id,
            "seconds_accum": self.seconds_accum,
            "playlist_length": self.playlist_length,
            "playlist_total_runtime": self.playlist_total_runtime,
            "second_expected": self.second_expected,
            "jellyfin_user_id": self.jellyfin_user_id,
            "track_started_at": self.track_started_at.isoformat() if self.track_started_at else None,
        }