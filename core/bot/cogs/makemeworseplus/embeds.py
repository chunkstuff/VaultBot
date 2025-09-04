# core/bot/cogs/vaultpulse/embeds.py
import discord
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Optional
from core.events.playlist_events import (
    PlaylistCreateEvent, 
    PlaylistCompleteEvent,
    PlaylistStartEvent,
    PlaylistTrackAdvanceEvent,
    PlaylistSwitchAwayEvent,
    PlaylistTrackJumpEvent,
    PlaylistSessionAbandonedEvent,
    PlaylistSessionPausedEvent,
    PlaylistSessionWaitingEvent,
    PlaylistSessionResumedEvent
)

def _create_base_embed(
    title: str, 
    description: str, 
    color: discord.Color, 
    timestamp: datetime,
    username: str,
    avatar_url: Optional[str] = None,
    user_playlist_id: Optional[int] = None,
    session_id: Optional[int] = None
) -> discord.Embed:
    """Create a base embed with consistent styling"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=timestamp
    )
    
    if avatar_url:
        embed.set_author(name=username, icon_url=avatar_url)
    
    # Add cryptic footer with just the numbers
    footer_parts = []
    if user_playlist_id:
        footer_parts.append(str(user_playlist_id))
    if session_id:
        footer_parts.append(f"#{session_id}")
    
    if footer_parts:
        embed.set_footer(text=" | ".join(footer_parts))
    
    return embed

def _format_track_title(title: Optional[str], item_id: str) -> str:
    """Format track title, falling back to item ID in backticks"""
    return title or f"`{item_id}`"

def _get_ordinal(n: int) -> str:
    """Convert number to ordinal (1st, 2nd, 3rd, etc.)"""
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def _format_time_spent(seconds: float) -> str:
    """Format seconds as readable time"""
    return f"(+{int(seconds)}s)"

# ------------------------
# Creation / Completion embeds
# ------------------------

def create_playlist_embed(event: PlaylistCreateEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create minimal embed for playlist creation"""
    return _create_base_embed(
        title="🎵 Playlist Created",
        description=f"{event.discord_username} created **{event.playlist_name}**",
        color=discord.Color.green(),
        timestamp=event.created_at,
        username=event.discord_username,
        avatar_url=avatar_url
    )

def create_completion_embed(event: PlaylistCompleteEvent, nth_playlist: int = 1, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create minimal embed for playlist completion"""
    ordinal = _get_ordinal(nth_playlist)
    
    return _create_base_embed(
        title="🎉 Playlist Complete",
        description=f"{event.discord_username} completed their **{ordinal}** playlist",
        color=discord.Color.gold(),
        timestamp=event.completion_time,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

# ------------------------
# Runtime embeds
# ------------------------

def create_start_embed(event: PlaylistStartEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Quiet "now playing" style embed when a user starts a playlist"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id)
    description = (
        f"{event.discord_username} started **{event.playlist_name}**\n"
        f"Track **#{event.current_index + 1}/{event.total_tracks}** — {track_title}"
    )
    
    return _create_base_embed(
        title="▶️ Now Playing",
        description=description,
        color=discord.Color.blurple(),
        timestamp=event.started_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_track_advance_embed(event: PlaylistTrackAdvanceEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Quiet update when the user moves to the next track within the same playlist"""
    from_title = _format_track_title(event.from_item_title, event.from_item_id)
    to_title = _format_track_title(event.to_item_title, event.to_item_id)
    time_spent = _format_time_spent(event.seconds_on_from)
    
    description = (
        f"Advanced **#{event.from_index + 1} → #{event.to_index + 1}** ({from_title}) {time_spent}\n"
        f"**Now playing:** {to_title}"
    )
    
    return _create_base_embed(
        title="⏭️ Track Advance",
        description=description,
        color=discord.Color.teal(),
        timestamp=event.occurred_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_track_jump_embed(event: PlaylistTrackJumpEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Quiet update when the user skips/jumps tracks"""
    from_title = _format_track_title(event.from_item_title, event.from_item_id)
    to_title = _format_track_title(event.to_item_title, event.to_item_id)
    time_spent = _format_time_spent(event.seconds_on_from)
    
    description = (
        f"Advanced **#{event.from_index + 1} → #{event.to_index + 1}** {from_title} {time_spent}\n"
        f"**Now playing:** {to_title}"
    )
    
    return _create_base_embed(
        title="⏭️ Track Skip",
        description=description,
        color=discord.Color.yellow(),
        timestamp=event.occurred_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_switch_away_embed(
    event: PlaylistSwitchAwayEvent,
    *,
    playlist_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> discord.Embed:
    """Quiet update when the user leaves the playlist"""
    from_title = _format_track_title(event.from_item_title, event.from_item_id)
    to_title = _format_track_title(event.switched_to_item_title, event.switched_to_item_id) if event.switched_to_item_id else "unknown"
    time_spent = _format_time_spent(event.seconds_on_from)
    pl_name = f"**{playlist_name}**" if playlist_name else f"playlist #{event.user_playlist_id}"
    
    description = (
        f"Left {pl_name} at **#{event.from_index + 1}** {time_spent}\n"
        f"{from_title} → {to_title}"
    )
    
    return _create_base_embed(
        title="⏸️ Switched Away",
        description=description,
        color=discord.Color.orange(),
        timestamp=event.occurred_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_abandoned_embed(event: PlaylistSessionAbandonedEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed when user abandons a playlist session (stops streaming entirely)"""
    last_track = _format_track_title(event.last_item_title, event.last_item_id)
    time_spent = _format_time_spent(event.seconds_on_last)
    
    description = (
        f"Abandoned **{event.playlist_name}** at **#{event.last_index + 1}** {time_spent}\n"
        f"Last track: {last_track}"
    )
    
    return _create_base_embed(
        title="🛑 Session Abandoned",
        description=description,
        color=discord.Color.red(),
        timestamp=event.abandoned_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_paused_embed(event: PlaylistSessionPausedEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed for session paused (5 minutes absent)"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id)
    
    return _create_base_embed(
        title="⏸️ Session Paused", 
        description=f"Stepped away from **{event.playlist_name}** at track **#{event.current_index + 1}**\n{track_title}\n",
        color=discord.Color.orange(),
        timestamp=event.paused_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_waiting_embed(event: PlaylistSessionWaitingEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed for session waiting for abandonment (15+ minutes absent)"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id)
    
    return _create_base_embed(
        title="⏰ Session Will Be Abandoned Soon",
        description=f"Away for **{event.minutes_absent:.0f} minutes** from **{event.playlist_name}** at track **#{event.current_index + 1}**\n{track_title}\n",
        color=discord.Color.from_rgb(255, 107, 53),  # Red-orange  
        timestamp=event.waiting_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_resumed_embed(event: PlaylistSessionResumedEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed for session resumed after being paused/waiting"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id)
    
    return _create_base_embed(
        title="▶️ Session Resumed",
        description=f"Returned to **{event.playlist_name}** after **{event.minutes_away:.0f} minutes** at track **#{event.current_index + 1}**\n{track_title}\n",
        color=discord.Color.green(),
        timestamp=event.resumed_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )
