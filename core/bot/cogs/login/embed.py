# core/bot/cogs/login/embed.py

import discord
from discord import Embed
from config.settings import settings
from utils.logger_factory import setup_logger
from .view import LoginButton

logger = setup_logger(__name__)

async def send_login_embed(bot: discord.Client) -> discord.Message | None:
    cfg = settings.get_embed_config("login_embed")

    embed = Embed(color=0xEBE84B)  # Hex color for login embed
    embed.set_image(url=cfg.get("image_url", ""))

    try:
        channel = bot.get_channel(settings.LOGIN_CHANNEL)
        if not isinstance(channel, discord.TextChannel):
            logger.error("❌ LOGIN_CHANNEL is missing or invalid.")
            return None

        if cfg.get("channel_id") and cfg.get("message_id"):
            try:
                msg = await channel.fetch_message(int(cfg["message_id"]))
                await msg.edit(embed=embed, view=LoginButton())
                logger.info(f"🔁 Updated login embed in channel {channel.id}")
                return msg
            except Exception as e:
                logger.warning(f"⚠️ Failed to update login embed: {e}")

        # Send new embed
        new_msg = await channel.send(embed=embed, view=LoginButton())
        settings.save_login_embed(channel.id, new_msg.id)
        logger.info(f"📌 Sent new login embed to channel {channel.id}")
        return new_msg

    except Exception:
        logger.exception("❌ Failed to send login embed")
        return None
