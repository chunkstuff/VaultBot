import discord
from discord import Embed, TextChannel
from config.settings import settings
from .state import registration_state
from .view import RegisterView, SingleUseRegisterView
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)

async def send_register_embed(bot: discord.Client) -> list[discord.Message]:
    cfg = settings.get_embed_config("register_embed")

    embed = discord.Embed(
        title=cfg.get("title", "Register for The Vault+"),
        description=cfg.get("description", "Click below to register."),
        color=discord.Color.blurple()
    )
    if image_url := cfg.get("image_url"):
        embed.set_thumbnail(url=image_url)
    if footer := cfg.get("footer"):
        embed.set_footer(text=footer)

    view = RegisterView() if registration_state.can_register() else None
    if not registration_state.open:
        embed.title = "<:vaultplus:1370425492649283604> Registration is now closed."
        embed.description = "🚫 Pre-seats for The Vault+ have all been filled. See you Friday, piggy!"
        view = None
    elif registration_state.is_full():
        embed.title = "<:vaultplus:1370425492649283604> Registration is now full, piggies!"
        embed.description = "⚠️ Oof, you missed it! This round of The Vault+ registration is now full. Check back soon, piggy!"
        view = None

    sent_messages = []

    # Try to update previously saved messages
    for entry in cfg.get("messages", []):
        try:
            ch = bot.get_channel(entry["channel_id"])
            if not isinstance(ch, discord.TextChannel):
                raise TypeError("Invalid channel type")
            msg = await ch.fetch_message(entry["message_id"])
            await msg.edit(embed=embed, view=view)
            sent_messages.append(msg)
            logger.info(f"🔁 Updated register embed in channel {ch.id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update message {entry}: {e}")

    # Send new messages to any missing channels
    for channel_id in {settings.LOGIN_CHANNEL}:
        if any(m.channel.id == channel_id for m in sent_messages):
            continue
        try:
            ch = bot.get_channel(channel_id)
            if not isinstance(ch, discord.TextChannel):
                logger.warning(f"❌ Cannot send embed to channel {channel_id}: not a text channel.")
                continue
            msg = await ch.send(embed=embed, view=view)
            sent_messages.append(msg)
        except Exception as e:
            logger.exception(f"❌ Failed to send new embed to channel {channel_id}: {e}")

    try:
        settings.save_register_embeds(sent_messages)
    except Exception as e:
        logger.exception(f"❌ Failed to save embed references: {e}")

    return sent_messages

async def send_single_use_register_embed(channel: TextChannel) -> discord.Message | None:
    embed = Embed(
        title="🎯 One-Time Vault+ Registration",
        description="Click below to register. This link is valid for one use only.",
        color=discord.Color.orange()
    )

    view = SingleUseRegisterView()

    try:
        msg = await channel.send(embed=embed, view=view)
        logger.info(f"🎯 Sent single-use register embed to channel {channel.id}")
        return msg
    except Exception as e:
        logger.exception("❌ Failed to send single-use register embed")
        return None
