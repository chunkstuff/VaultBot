# core/bot/cogs/vaultpulse/listeners.py
import asyncio
import traceback
import discord
from discord.ext import commands
from typing import Optional, Callable
from dataclasses import dataclass

from core.jellyfin_client import JellyfinClient
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
    PlaylistSessionResumedEvent,
)
from .embeds import (
    create_playlist_embed,
    create_completion_embed,
    create_start_embed,
    create_track_advance_embed,
    create_switch_away_embed,
    create_track_jump_embed,
    create_session_abandoned_embed,
    create_session_paused_embed,
    create_session_waiting_embed,
    create_session_resumed_embed,
)
from .playlist_deletion import delete_playlist
from .playlist_tracking_db_helpers import (
    get_completed_playlist_count,
    get_playlist_info,
)
from utils.logger_factory import setup_logger
from config.settings import settings

logger = setup_logger(__name__)

@dataclass
class MessageStrategy:
    """Defines how to handle Discord messages for different event types"""
    should_replace: bool  # Whether to replace previous "now playing" message
    should_cleanup: bool  # Whether to clean up tracking after event

class PlaylistListeners(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # remember the last "now playing" message per (discord_user_id, user_playlist_id)
        self._last_np_msg: dict[tuple[str, int], int] = {}
        self._msg_lock = asyncio.Lock()

        # Define strategies for different event types
        self._strategies = {
            'start': MessageStrategy(should_replace=True, should_cleanup=False),
            'advance': MessageStrategy(should_replace=True, should_cleanup=False),
            'jump': MessageStrategy(should_replace=True, should_cleanup=False),
            'switch_away': MessageStrategy(should_replace=False, should_cleanup=False),
            'abandoned': MessageStrategy(should_replace=False, should_cleanup=True),
            'paused': MessageStrategy(should_replace=True, should_cleanup=False),
            'waiting': MessageStrategy(should_replace=True, should_cleanup=False),
            'resumed': MessageStrategy(should_replace=True, should_cleanup=False),
        }

    async def _get_user_avatar_url(self, discord_user_id: str) -> Optional[str]:
        """Get user avatar URL, returns None if user not found"""
        try:
            user = self.bot.get_user(int(discord_user_id))
            return user.display_avatar.url if user else None
        except (ValueError, AttributeError):
            return None

    async def _send_replacing(
        self,
        key: tuple[str, int],
        channel: discord.TextChannel,
        embed: discord.Embed,
    ) -> None:
        """Delete the previous message for this key, then send the new one."""
        async with self._msg_lock:
            old_id = self._last_np_msg.get(key)
            if old_id:
                try:
                    old_msg = await channel.fetch_message(old_id)
                    await old_msg.delete()
                except Exception as e:
                    logger.debug(f"[PlaylistListeners] could not delete old now-playing msg {old_id}: {e}")

            msg = await channel.send(
                embed=embed,
                silent=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self._last_np_msg[key] = msg.id

    async def _send_non_replacing(
        self,
        channel: discord.TextChannel,
        embed: discord.Embed,
    ) -> None:
        """Send message without replacing previous ones."""
        await channel.send(
            embed=embed,
            silent=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _handle_playlist_runtime_event(
        self,
        event,
        embed_creator: Callable,
        strategy_key: str,
        log_message: str,
    ):
        """Generic handler for playlist runtime events (start, advance, jump, switch_away, abandoned)"""
        try:
            strategy = self._strategies[strategy_key]
            
            # Log the event
            logger.info(log_message)
            
            # Check if we should send Discord notification
            if not settings.NETWORK_CHANNEL:
                return
            channel = self.bot.get_channel(settings.NETWORK_CHANNEL)
            if not channel:
                return

            # Create embed
            avatar_url = await self._get_user_avatar_url(event.discord_user_id)
            embed = embed_creator(event, avatar_url)

            # Send message based on strategy
            if strategy.should_replace:
                key = (event.discord_user_id, event.user_playlist_id)
                await self._send_replacing(key, channel, embed)
            else:
                await self._send_non_replacing(channel, embed)
            
            # Clean up tracking if needed
            if strategy.should_cleanup:
                self._last_np_msg.pop((event.discord_user_id, event.user_playlist_id), None)

        except Exception as e:
            logger.error(f"on_{strategy_key} error: {e}")
            logger.error(traceback.format_exc())

    # ------------------------
    # Creation / Completion (Special cases)
    # ------------------------

    @commands.Cog.listener()
    async def on_playlist_create(self, event: PlaylistCreateEvent):
        """Handle playlist creation - simple notification"""
        logger.info(f"Playlist created: {event.playlist_name} by {event.discord_username}")

        if settings.NETWORK_CHANNEL:
            channel = self.bot.get_channel(settings.NETWORK_CHANNEL)
            if channel:
                avatar_url = await self._get_user_avatar_url(event.discord_user_id)
                embed = create_playlist_embed(event, avatar_url)
                await channel.send(embed=embed, silent=True)

    @commands.Cog.listener()
    async def on_playlist_complete(self, event: PlaylistCompleteEvent):
        """Handle playlist completion - includes playlist deletion logic"""
        try:
            logger.info(f"Playlist completed: {event.playlist_name} by {event.discord_username}")

            if settings.NETWORK_CHANNEL:
                channel = self.bot.get_channel(settings.NETWORK_CHANNEL)
                if channel:
                    avatar_url = await self._get_user_avatar_url(event.discord_user_id)
                    total_completed = await self._get_user_playlist_count(event.discord_user_id)

                    embed = create_completion_embed(event, total_completed, avatar_url)
                    await channel.send(embed=embed, silent=True)

            # Clean up tracking for this playlist
            self._last_np_msg.pop((event.discord_user_id, event.user_playlist_id), None)

            # Delete the Jellyfin playlist
            jellyfin_client: JellyfinClient | None = getattr(self.bot, "client", None)
            if jellyfin_client and event.playlist_id:
                vault_db = jellyfin_client.users.sessions.user_session_db
                deletion_success = await delete_playlist(jellyfin_client, vault_db, event.playlist_id)
                if deletion_success:
                    logger.info(
                        f"Deleted Jellyfin playlist {event.playlist_id} after completion by {event.discord_username}"
                    )
                else:
                    logger.warning(
                        f"Failed to delete Jellyfin playlist {event.playlist_id} for {event.discord_username}"
                    )
        except Exception as e:
            logger.error(f"Unexpected error! {e}")
            logger.error(traceback.format_exc())

    async def _get_user_playlist_count(self, discord_user_id: str) -> int:
        """Get total number of playlists this user has completed"""
        return await get_completed_playlist_count(
            self.bot.client.users.sessions.user_session_db, discord_user_id
        )

    # ------------------------
    # Runtime events (using generic handler)
    # ------------------------

    @commands.Cog.listener()
    async def on_playlist_start(self, event: PlaylistStartEvent):
        """Handle playlist start"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_start_embed,
            strategy_key='start',
            log_message=f"Start: {event.playlist_name} @ {event.current_index + 1} by {event.discord_username}"
        )

    @commands.Cog.listener()
    async def on_playlist_track_advance(self, event: PlaylistTrackAdvanceEvent):
        """Handle track advance"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_track_advance_embed,
            strategy_key='advance',
            log_message=f"Advance: {event.user_playlist_id} {event.from_index + 1}->{event.to_index + 1}"
        )

    @commands.Cog.listener()
    async def on_playlist_track_jump(self, event: PlaylistTrackJumpEvent):
        """Handle track jump/skip"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_track_jump_embed,
            strategy_key='jump',
            log_message=f"Jump: {event.user_playlist_id} {event.from_index + 1}->{event.to_index + 1}"
        )

    @commands.Cog.listener()
    async def on_playlist_switch_away(self, event: PlaylistSwitchAwayEvent):
        """Handle switching away from playlist"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=lambda e, avatar: create_switch_away_embed(
                e, playlist_name=e.playlist_name, avatar_url=avatar
            ),
            strategy_key='switch_away',
            log_message=f"Switch-away: playlist {event.playlist_name} at {event.from_index + 1}"
        )

    @commands.Cog.listener()
    async def on_playlist_session_abandoned(self, event: PlaylistSessionAbandonedEvent):
        """Handle session abandonment"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_session_abandoned_embed,
            strategy_key='abandoned',
            log_message=f"Session abandoned: playlist {event.playlist_name} at {event.last_index + 1} by {event.discord_username}"
        )

    @commands.Cog.listener()
    async def on_playlist_session_paused(self, event: PlaylistSessionPausedEvent):
        """Handle playlist session paused events (5 minutes absent)"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_session_paused_embed,
            strategy_key='paused',
            log_message=f"Session paused: {event.playlist_name} by {event.discord_username} (5 min absent)"
        )

    @commands.Cog.listener()
    async def on_playlist_session_waiting(self, event: PlaylistSessionWaitingEvent):
        """Handle playlist session waiting events (15+ minutes absent)"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_session_waiting_embed,
            strategy_key='waiting',
            log_message=f"Session waiting: {event.playlist_name} by {event.discord_username} (15 min absent)"
        )

    @commands.Cog.listener()
    async def on_playlist_session_resumed(self, event: PlaylistSessionResumedEvent):
        """Handle playlist session resumed events (user returns after pause/wait)"""
        await self._handle_playlist_runtime_event(
            event=event,
            embed_creator=create_session_resumed_embed,
            strategy_key='resumed',
            log_message=f"Session resumed: {event.playlist_name} by {event.discord_username} (away {event.minutes_away:.0f} min)"
        )