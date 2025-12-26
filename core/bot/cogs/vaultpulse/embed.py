# core/bot/cogs/vaultpulse/embed.py

from concurrent.futures import Executor
from inspect import trace
import json
import traceback
import aiohttp
import discord
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


from config.time_helpers import format_ticks
from config.settings import settings
from utils.logger_factory import setup_logger
from core.bot.test_helpers import get_guild

logger = setup_logger(__name__)


class EmbedBuilder:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self._last_user_fetch = None
        self._cached_users = []

    async def build_status_embed(self, active: int, streaming: int, streamers: list[dict]) -> discord.Embed:
        try:
            uk_time = datetime.now(ZoneInfo("Europe/London"))
            timestamp = int(uk_time.timestamp())

            all_users = await self.get_cached_users()
            recent_users = self._get_recent_users(all_users)
            now_listening = self._count_active_streamers(streamers)

            top_listener_text = await self.db.get_top_listeners_text(self.bot.link_map)

            embed = self._create_embed(active, streaming, now_listening, recent_users, all_users, timestamp, top_listener_text)

            streamers.sort(key=self._stream_sort_key)
            guild = get_guild(self.bot)
            return await self._populate_streamer_fields(streamers, embed, guild)
        except Exception as e:
            logger.error(f'Unexpected error! {e}')
            logger.error(traceback.format_exc())

    async def update_or_send_embed(self, embed: discord.Embed):
        try:
            config_key = "status_embed"
            config = settings.config
            cfg = config.get(config_key, {})
            channel_id = cfg.get("channel_id")
            message_id = cfg.get("message_id")
            
            max_retries = 3
            retry_delay = 2
            
            for attempt in range(max_retries):
                try:
                    channel = self.bot.get_channel(channel_id) if channel_id else None
                    if not channel and channel_id:
                        channel = await self.bot.fetch_channel(channel_id)
                    
                    if channel and message_id:
                        try:
                            message = await channel.fetch_message(message_id)
                            await message.edit(embed=embed)
                            
                            # Only log if it's a retry (not first attempt)
                            if attempt > 0:
                                logger.info(f"Status embed updated successfully on attempt {attempt + 1}")
                            return  # Success - exit completely
                            
                        except Exception as e:
                            logger.warning(f"Failed to update existing message on attempt {attempt + 1}: {e}")
                            
                            if attempt == max_retries - 1:
                                logger.info("Max retries reached, creating new message")
                                break
                            else:
                                await asyncio.sleep(retry_delay)
                                continue
                    
                    # No existing message, create new one
                    target = self.bot.get_channel(settings.DASHBOARD_CHANNEL) or await self.bot.fetch_channel(settings.DASHBOARD_CHANNEL)
                    msg = await target.send(embed=embed)
                    config[config_key] = {"channel_id": msg.channel.id, "message_id": msg.id}
                    settings._write_config(config)

                    logger.info(f"New status embed sent successfully on attempt {attempt + 1}")
                    return
                    
                except Exception as e:
                    logger.error(f"Failed to send embed on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f'Unexpected error! {e}')
            logger.error(traceback.format_exc())

    async def _send_webhook_embed(self, embed: discord.Embed, webhook_url: str):
        """
        Send the given embed via a Discord webhook URL.
        """
        avatar = getattr(self.bot.user, "avatar", None)
        avatar_url = str(avatar.url) if avatar else ""

        data = {
            "embeds": [embed.to_dict()],
            "username": "Vault+ Status",
            "avatar_url": avatar_url
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=data) as resp:
                if resp.status not in (200, 204, 201):
                    logger.error(f"Webhook POST failed ({resp.status}): {await resp.text()}")
                    raise Exception(f"Webhook POST failed: {resp.status}")


    def _stream_sort_key(self, s):
        state = s.get("PlayState", {})
        is_playing = not state.get("IsPaused", False)
        position = state.get("PositionTicks", 0)
        return (not is_playing, -position)

    def _count_active_streamers(self, streamers):
        return sum(not s.get("PlayState", {}).get("IsPaused", False) for s in streamers) or "👀 Nobody..."

    def _get_recent_users(self, all_users):
        cutoff = datetime.utcnow() - timedelta(hours=24)
        return [u for u in all_users if (ts := u.get("LastActivityDate")) and datetime.fromisoformat(ts.rstrip("Z")) > cutoff]

    async def get_cached_users(self):
        now = datetime.utcnow()
        if not self._last_user_fetch or (now - self._last_user_fetch) > timedelta(minutes=15):
            try:
                self._cached_users = await self.bot.client.api.get("/Users")
                self._last_user_fetch = now
            except Exception as e:
                logger.error(f"Failed to fetch users: {e}")
        return self._cached_users

    def _create_embed(self, active, streaming, now_listening, recent_users, all_users, timestamp, top_listener_text):
        return discord.Embed(
            title="🔴 Vault+ Server Status",
            description=(
                f"**Active sessions:** {active}\n"
                f"**Users streaming:** {streaming}\n"
                f"**Sinking for Sir:** {now_listening}\n\n"
                f"{top_listener_text}\n\n"
                f"**Users active in last 24h:** {len(recent_users)} / {len(all_users)}\n\n"
                f"-# **Last update:** <t:{timestamp}:f>"
            ),
            color=0xff4757
        )
    async def _populate_streamer_fields(self, streamers, embed, guild):
        # Ensure we have a valid guild in test mode
        if not guild:
            guild = get_guild(self.bot)
        
        for s in streamers[:24]:
            jf_id = s.get("UserId")
            mention = await self._resolve_discord_mention(jf_id, guild)
            field = self._parse_stream_data(s, mention)
            embed.add_field(**field)
        return embed


    async def _resolve_discord_mention(self, jf_id: str, guild: discord.Guild) -> str:
        return await self.bot.link_map.get_discord_mention(jf_id, guild)

    def _parse_stream_data(self, s: dict, mention: str) -> dict:
        jf_username = s.get("UserName", "Unknown")
        item = s.get("NowPlayingItem", {})
        title = item.get("Name", "Unknown Title")

        ticks = s.get("PlayState", {}).get("PositionTicks", 0)
        duration_ticks = item.get("RunTimeTicks", 0)
        current = format_ticks(ticks)
        total = format_ticks(duration_ticks)
        emoji = "⏸️" if s.get("PlayState", {}).get("IsPaused", False) else "▶️"

        return {
            "name": f"{emoji} {jf_username} <:vaultplus:1370425492649283604>",
            "value": f"**{title}** – `{current} / {total}`\n-# {mention}\n{'─' * 45}",
            "inline": False
        }
