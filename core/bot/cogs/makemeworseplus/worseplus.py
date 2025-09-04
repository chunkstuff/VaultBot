# core/bot/cogs/makemeworseplus/worseplus.py

import discord
import asyncio
import traceback
from datetime import datetime
from discord.ext import commands, tasks
from config.settings import settings
from utils.logger_factory import setup_logger
from .view import WorseView
from .playlist_utils import expire_and_delete_old_playlists
import json
from pathlib import Path
import re

logger = setup_logger(__name__)
COLLECTIONS_AND_TAGS_PATH = Path("config/collections_and_tags.json")

class MakeMeWorsePlus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        data = self.load_collections_and_tags()
        self.collection_list = data.get("collections", [])
        self.tags_list = data.get("tags", [])
        self.view = WorseView(bot, self.collection_list, self.tags_list)
        self.bot.add_view(self.view)
        logger.info(f"[GetWorse] ✅ loaded with collections: {len(self.collection_list)}, tags: {len(self.tags_list)}")

        self._tasks_started = False

    # ---------- background expiry task ----------

    def _get_vault_db(self):
        """
        Resolve VaultPulseDB: bot.client.dbase.vault_pulse_db
        """
        dbase = getattr(getattr(self.bot, "client", None), "dbase", None)
        return getattr(dbase, "vault_pulse_db", None)

    async def cog_load(self):
        # discord.py 2.x lifecycle hook: start background tasks here
        if not self._tasks_started:
            logger.info("[MakeMeWorsePlus] Starting background tasks (cog_load).")
            self.expire_old_playlists_task.start()
            self._tasks_started = True
            logger.info("[MakeMeWorsePlus] Background tasks started.")

    async def cog_unload(self):
        logger.info("[MakeMeWorsePlus] Cog unloading, cancelling tasks...")
        if self.expire_old_playlists_task.is_running():
            self.expire_old_playlists_task.cancel()

    @tasks.loop(minutes=30)
    async def expire_old_playlists_task(self):
        vault_db = self._get_vault_db()
        if not vault_db:
            # Not fatal; just wait for next tick (bot may still be starting up)
            logger.debug("[MakeMeWorsePlus] vault_db not available yet; skipping expiry tick.")
            return
        try:
            count = await expire_and_delete_old_playlists(vault_db, self.bot.client)
            if count:
                logger.info(f"[MakeMeWorsePlus] Expired {count} playlists (>48h).")
        except Exception as e:
            logger.error(f"[MakeMeWorsePlus] expire_old_playlists_task error: {e}")
            logger.error(traceback.format_exc())

    @expire_old_playlists_task.before_loop
    async def before_expire_old_playlists_task(self):
        """
        Align to the next :00 or :30 boundary to keep logs neat.
        """
        try:
            logger.info("[MakeMeWorsePlus] expire_old_playlists_task about to start looping.")
            # await self.bot.wait_until_ready()  # optional if you want to wait for ready
            now = datetime.utcnow()
            # seconds until next half-hour mark
            seconds = ((30 - (now.minute % 30)) * 60) - now.second
            if seconds <= 0:
                seconds += 1800
            await asyncio.sleep(seconds)
        except RuntimeError as e:
            logger.info(f"[MakeMeWorsePlus] Bot shutdown during before_loop: {e}")
            return  # Exit cleanly

    # ---------- collections and tags management ----------

    def load_collections_and_tags(self):
        with COLLECTIONS_AND_TAGS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)

    def reload_collections_and_tags(self):
        data = self.load_collections_and_tags()
        self.collection_list = data.get("collections", [])
        self.tags_list = data.get("tags", [])
        self.view.collection_list = self.collection_list
        self.view.tags_list = self.tags_list
        print("🔁 Collections and tags hot reloaded")

    async def send_worse_embed(self):
        await self._post_or_update_embed()
        logger.info('🤝 Sent MakeMeWorsePlus embed')

    async def _post_or_update_embed(self):
        config_key = "makeworse_embed"
        cfg = settings.get_embed_config(config_key)

        embed = discord.Embed(
            title=cfg.get("title"),
            description=cfg.get("description"),
            color=0x8e44ad,
        )

        if image_url := cfg.get("image_url"):
            embed.set_thumbnail(url=image_url)
        if footer := cfg.get("footer"):
            embed.set_footer(text=footer)

        channel_id = cfg.get("channel_id")
        message_id = cfg.get("message_id")
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not channel and channel_id:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logger.warning(f"Failed to fetch channel: {e}")

        if channel and message_id:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed, view=self.view)
                logger.info(f"🔁 Updated worseplus embed in channel {channel.id}")
                return
            except Exception as e:
                logger.warning(f"Failed to update existing message: {e}")

        # 🆕 Fresh post if needed
        try:
            target = self.bot.get_channel(settings.WORSE_PLUS_CHANNEL) or await self.bot.fetch_channel(settings.WORSE_PLUS_CHANNEL)
            msg = await target.send(embed=embed, view=self.view)
            settings.save_worse_embed(msg.channel.id, msg.id)
        except Exception as e:
            logger.error(f"Failed to send Worse+ embed: {e}")