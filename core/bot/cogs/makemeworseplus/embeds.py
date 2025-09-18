# core/bot/cogs/makemeworseplus/embeds.py
import discord
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Optional, List
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

def _format_track_title(title: Optional[str], item_id: str, max_length: int = 40) -> str:
    """Format track title, falling back to item ID in backticks"""
    if not title:
        return f"`{item_id[:8]}...`"
    
    # Truncate long titles
    if len(title) > max_length:
        return f"{title[:max_length-3]}..."
    return title

def _get_ordinal(n: int) -> str:
    """Convert number to ordinal (1st, 2nd, 3rd, etc.)"""
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def _format_time_spent(seconds: float) -> str:
    """Format seconds as readable time"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s" if secs > 0 else f"{mins}m"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"

def _format_playlist_items(items: List[dict], current_index: Optional[int] = None) -> str | dict:
    """Format playlist items in a proper two-column layout using Discord formatting"""
    if not items:
        return "No tracks available"
    
    # For very short playlists, just show them in a single column
    if len(items) <= 4:
        lines = []
        for i, track in enumerate(items):
            track_num = i + 1
            title = _format_track_title(track.get('title'), track.get('id', ''), max_length=50)
            
            if current_index is not None and i == current_index:
                lines.append(f"**{track_num}. {title}** ▶️")
            else:
                lines.append(f"{track_num}. {title}")
        
        return "```\n" + "\n".join(lines) + "\n```"
    
    # For longer playlists, use two fields side by side
    mid_point = (len(items) + 1) // 2
    left_items = items[:mid_point]
    right_items = items[mid_point:]
    
    # Format left column
    left_lines = []
    for i, track in enumerate(left_items):
        track_num = i + 1
        title = _format_track_title(track.get('title'), track.get('id', ''), max_length=30)
        
        if current_index is not None and i == current_index:
            left_lines.append(f"**{track_num}. {title}** ▶️")
        else:
            left_lines.append(f"{track_num}. {title}")
    
    # Format right column
    right_lines = []
    for i, track in enumerate(right_items):
        track_num = mid_point + i + 1
        title = _format_track_title(track.get('title'), track.get('id', ''), max_length=30)
        
        if current_index is not None and (mid_point + i) == current_index:
            right_lines.append(f"**{track_num}. {title}** ▶️")
        else:
            right_lines.append(f"{track_num}. {title}")
    
    # Return as two separate columns that Discord will display side by side
    left_column = "```\n" + "\n".join(left_lines) + "\n```"
    right_column = "```\n" + "\n".join(right_lines) + "\n```" if right_lines else ""
    
    return {"left": left_column, "right": right_column}

# ------------------------
# Creation / Completion embeds
# ------------------------

def create_playlist_embed(event: PlaylistCreateEvent, avatar_url: Optional[str] = None, 
                         playlist_items: Optional[List[dict]] = None) -> discord.Embed:
    """Create enhanced embed for playlist creation with track listing"""
    description = f"{event.discord_username} created **{event.playlist_name}**\n"
    description += f"**{event.num_files} tracks** from collections: {', '.join(event.collections[:3])}"
    if len(event.collections) > 3:
        description += f" (+{len(event.collections) - 3} more)"
    
    embed = _create_base_embed(
        title="🎵 Playlist Created",
        description=description,
        color=discord.Color.green(),
        timestamp=event.created_at,
        username=event.discord_username,
        avatar_url=avatar_url
    )
    
    # Add playlist items if provided
    if playlist_items:
        formatted_items = _format_playlist_items(playlist_items)
        
        if isinstance(formatted_items, dict):
            # Two-column layout
            embed.add_field(
                name=f"",
                value=formatted_items["left"],
                inline=True
            )
            if formatted_items["right"]:
                mid_point = (len(playlist_items) + 1) // 2
                embed.add_field(
                    name=f"",
                    value=formatted_items["right"],
                    inline=True
                )
        else:
            # Single column layout
            embed.add_field(
                name=f"",
                value=formatted_items,
                inline=False
            )
    
    return embed

def create_completion_embed(event: PlaylistCompleteEvent, nth_playlist: int = 1, 
                           avatar_url: Optional[str] = None) -> discord.Embed:
    """Create minimal embed for playlist completion"""
    ordinal = _get_ordinal(nth_playlist)
    listen_time = ""
    if event.listen_duration:
        listen_time = f" in {_format_time_spent(event.listen_duration)}"
    
    description = f"{event.discord_username} completed their **{ordinal}** playlist{listen_time}"
    
    return _create_base_embed(
        title="🎉 Playlist Complete",
        description=description,
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

def create_start_embed(event: PlaylistStartEvent, avatar_url: Optional[str] = None,
                      playlist_items: Optional[List[dict]] = None) -> discord.Embed:
    """Enhanced "now playing" embed with full playlist view"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id)
    description = (
        f"**{event.playlist_name}**\n"
        f"▶️ **Track {event.current_index + 1}/{event.total_tracks}:** {track_title}"
    )
    
    embed = _create_base_embed(
        title="🎵 Started Playlist",
        description=description,
        color=discord.Color.blurple(),
        timestamp=event.started_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )
    
    # Add playlist items if provided
    if playlist_items:
        formatted_items = _format_playlist_items(playlist_items, event.current_index)
        
        if isinstance(formatted_items, dict):
            # Two-column layout
            embed.add_field(
                name=f"📋 Tracks 1-{(len(playlist_items) + 1) // 2}",
                value=formatted_items["left"],
                inline=True
            )
            if formatted_items["right"]:
                mid_point = (len(playlist_items) + 1) // 2
                embed.add_field(
                    name=f"📋 Tracks {mid_point + 1}-{len(playlist_items)}",
                    value=formatted_items["right"],
                    inline=True
                )
        else:
            # Single column layout
            embed.add_field(
                name=f"📋 Playlist ({len(playlist_items)} tracks)",
                value=formatted_items,
                inline=False
            )
    
    return embed

def create_track_advance_embed(event: PlaylistTrackAdvanceEvent, avatar_url: Optional[str] = None,
                              playlist_items: Optional[List[dict]] = None, 
                              playlist_name: Optional[str] = None) -> discord.Embed:
    """Enhanced track advance embed with better formatting"""
    from_title = _format_track_title(event.from_item_title, event.from_item_id, max_length=30)
    to_title = _format_track_title(event.to_item_title, event.to_item_id, max_length=30)
    time_spent = _format_time_spent(event.seconds_on_from)
    
    # Calculate total tracks from playlist items if available
    total_tracks = len(playlist_items) if playlist_items else "?"
    
    description = (
        f"**{playlist_name or f'Playlist #{event.user_playlist_id}'}**\n"
        f"✅ **Track {event.from_index + 1}:** {from_title} *({time_spent})*\n"
        f"▶️ **Track {event.to_index + 1}/{total_tracks}:** {to_title}"
    )
    
    embed = _create_base_embed(
        title="⏭️ Track Complete",
        description=description,
        color=discord.Color.teal(),
        timestamp=event.occurred_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )
    
    # Add condensed playlist view showing progress
    if playlist_items:
        formatted_items = _format_playlist_items(playlist_items, event.to_index)
        
        if isinstance(formatted_items, dict):
            # Two-column layout
            embed.add_field(
                name=f"📋 Progress 1-{(len(playlist_items) + 1) // 2}",
                value=formatted_items["left"],
                inline=True
            )
            if formatted_items["right"]:
                mid_point = (len(playlist_items) + 1) // 2
                embed.add_field(
                    name=f"📋 Progress {mid_point + 1}-{len(playlist_items)}",
                    value=formatted_items["right"],
                    inline=True
                )
        else:
            # Single column layout
            embed.add_field(
                name=f"📋 Progress ({event.to_index + 1}/{len(playlist_items)})",
                value=formatted_items,
                inline=False
            )
    
    return embed

def create_track_jump_embed(event: PlaylistTrackJumpEvent, avatar_url: Optional[str] = None,
                           playlist_items: Optional[List[dict]] = None,
                           playlist_name: Optional[str] = None) -> discord.Embed:
    """Enhanced track jump embed"""
    from_title = _format_track_title(event.from_item_title, event.from_item_id, max_length=30)
    to_title = _format_track_title(event.to_item_title, event.to_item_id, max_length=30)
    time_spent = _format_time_spent(event.seconds_on_from)
    
    total_tracks = len(playlist_items) if playlist_items else "?"
    
    description = (
        f"**{playlist_name or f'Playlist #{event.user_playlist_id}'}**\n"
        f"⏩ **Skipped Track {event.from_index + 1}:** {from_title} *({time_spent})*\n"
        f"▶️ **Track {event.to_index + 1}/{total_tracks}:** {to_title}"
    )
    
    embed = _create_base_embed(
        title="⏭️ Track Skipped",
        description=description,
        color=discord.Color.yellow(),
        timestamp=event.occurred_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )
    
    if playlist_items:
        formatted_items = _format_playlist_items(playlist_items, event.to_index)
        
        if isinstance(formatted_items, dict):
            # Two-column layout
            embed.add_field(
                name=f"📋 Progress 1-{(len(playlist_items) + 1) // 2}",
                value=formatted_items["left"],
                inline=True
            )
            if formatted_items["right"]:
                mid_point = (len(playlist_items) + 1) // 2
                embed.add_field(
                    name=f"📋 Progress {mid_point + 1}-{len(playlist_items)}",
                    value=formatted_items["right"],
                inline=True
            )
        else:
            # Single column layout
            embed.add_field(
                name=f"📋 Progress ({event.to_index + 1}/{len(playlist_items)})",
                value=formatted_items,
                inline=False
            )
    
    return embed

def create_switch_away_embed(
    event: PlaylistSwitchAwayEvent,
    *,
    playlist_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> discord.Embed:
    """Improved switch away embed"""
    from_title = _format_track_title(event.from_item_title, event.from_item_id, max_length=35)
    to_title = _format_track_title(event.switched_to_item_title, event.switched_to_item_id, max_length=35) if event.switched_to_item_id else "unknown track"
    time_spent = _format_time_spent(event.seconds_on_from)
    pl_name = playlist_name or f"Playlist #{event.user_playlist_id}"
    
    description = (
        f"Left **{pl_name}** at track **{event.from_index + 1}**\n"
        f"⏸️ **Was playing:** {from_title} *({time_spent})*\n"
        f"🎵 **Now playing:** {to_title}"
    )
    
    return _create_base_embed(
        title="⏸️ Left Playlist",
        description=description,
        color=discord.Color.orange(),
        timestamp=event.occurred_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_abandoned_embed(event: PlaylistSessionAbandonedEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed when user abandons a playlist session"""
    last_track = _format_track_title(event.last_item_title, event.last_item_id, max_length=40)
    time_spent = _format_time_spent(event.seconds_on_last)
    
    description = (
        f"Abandoned **{event.playlist_name}** at track **{event.last_index + 1}**\n"
        f"⏹️ **Last track:** {last_track} *({time_spent})*"
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
    track_title = _format_track_title(event.current_item_title, event.current_item_id, max_length=40)
    
    description = (
        f"Stepped away from **{event.playlist_name}**\n"
        f"⏸️ **Paused at track {event.current_index + 1}:** {track_title}"
    )
    
    return _create_base_embed(
        title="⏸️ Session Paused", 
        description=description,
        color=discord.Color.orange(),
        timestamp=event.paused_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_waiting_embed(event: PlaylistSessionWaitingEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed for session waiting for abandonment (15+ minutes absent)"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id, max_length=40)
    
    description = (
        f"**{event.playlist_name}** will be abandoned soon\n"
        f"⏰ **Away for {event.minutes_absent:.0f} minutes** at track **{event.current_index + 1}**\n"
        f"🎵 {track_title}"
    )
    
    return _create_base_embed(
        title="⏰ Session Waiting",
        description=description,
        color=discord.Color.from_rgb(255, 107, 53),  # Red-orange  
        timestamp=event.waiting_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )

def create_session_resumed_embed(event: PlaylistSessionResumedEvent, avatar_url: Optional[str] = None) -> discord.Embed:
    """Create embed for session resumed after being paused/waiting"""
    track_title = _format_track_title(event.current_item_title, event.current_item_id, max_length=40)
    
    description = (
        f"Returned to **{event.playlist_name}** after **{event.minutes_away:.0f} minutes**\n"
        f"▶️ **Resuming track {event.current_index + 1}:** {track_title}"
    )
    
    return _create_base_embed(
        title="▶️ Session Resumed",
        description=description,
        color=discord.Color.green(),
        timestamp=event.resumed_at,
        username=event.discord_username,
        avatar_url=avatar_url,
        user_playlist_id=event.user_playlist_id,
        session_id=event.session_id
    )