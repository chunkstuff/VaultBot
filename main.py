import aiohttp
import asyncio
import signal
from discord import Intents

from config.settings import settings
from core.jellyfin_nav import JellyfinNavigator
from core.services.api import JellyfinAPI
from core.services.avatar_service import AvatarService
from core.services.user_service import UserService
from core.services.database_manager import DatabaseManager
from core.services.notifier import Notifier
from core.services.email_service import EmailService
from core.bot.bot import VaultBot
from core.jellyfin_client import JellyfinClient
from core.services.admin_notifier import AdminNotifier
from utils.logger_factory import setup_logger


logger = setup_logger(__name__)

shutdown_event = asyncio.Event()

async def shutdown():
    logger.info("Shutdown signal received.")
    shutdown_event.set()

async def create_sessions() -> dict:
    return {
        "api": aiohttp.ClientSession(headers=settings.HEADERS),
    }

# Example background task (optional)
async def background_worker():
    while not shutdown_event.is_set():
        logger.info("Background worker tick.")
        await asyncio.sleep(60)

async def start_bot():
    sessions = await create_sessions()
    dbase = DatabaseManager()
    await dbase.connect_all()
    bot = None

    try:
        intents = Intents.all()
        admin_notifier = AdminNotifier()
        registration_notifier = Notifier(email_service=EmailService())

        # Core Jellyfin components
        navigator = JellyfinNavigator(settings.JELLYFIN_URL, admin_notifier)
        api = JellyfinAPI(settings.JELLYFIN_URL, sessions["api"], admin_notifier)
        users = UserService(api, dbase, admin_notifier)
        avatars = AvatarService(navigator, admin_notifier)
        client = JellyfinClient(api, users, avatars)

        link_map = dbase.user_linker

        bot = VaultBot(
            client=client,
            link_map=link_map,
            admin_notifier=admin_notifier,
            registration_notifier=registration_notifier,
            command_prefix="!",
            intents=intents,
        )
        admin_notifier.bot = bot

        # await bot.load_extension("core.bot.cogs.register")
        await bot.load_extension("core.bot.cogs.login")
        await bot.load_extension("core.bot.cogs.vaultpulse")
        await bot.load_extension("core.bot.cogs.makemeworseplus")
        await bot.load_extension("core.bot.cogs.subscription_tracker")
        await bot.load_extension("core.bot.cogs.vaultplus_admin")

        # Create your bot and any background tasks
        bot_task = asyncio.create_task(bot.start(settings.DISCORD_TOKEN))
        # background_task = asyncio.create_task(background_worker())  # Uncomment if needed

        await shutdown_event.wait()

        # On shutdown, cancel tasks if running
        for t in [bot_task]:  # add background_task if used
            if not t.done():
                t.cancel()
        await asyncio.gather(bot_task, return_exceptions=True)
        # await asyncio.gather(bot_task, background_task, return_exceptions=True)  # Uncomment if needed

    except Exception as e:
        logger.exception(f"Unhandled exception in bot startup: {e}")
        if bot and hasattr(bot, "admin_notifier"):
            await bot.admin_notifier.send_admin_alert(str(e), context="Startup Failure")

    finally:
        # === FLUSH VAULTPULSE FIRST ===
        if bot:
            try:
                sm = bot.get_cog("VaultPulse")
                if sm:
                    logger.info("Flushing VaultPulse on shutdown...")
                    await sm.flush()
            except Exception as e:
                logger.warning(f"🧼 Flush on exit failed: {e}")

        # === CLOSE SESSIONS ===
        logger.info("🧹 Cleaning up sessions...")
        for name, session in sessions.items():
            if not session.closed:
                await session.close()
                logger.debug(f"Closed session: {name}")

        # === CLOSE DATABASE CONNECTION ===
        try:
            await dbase.close_all()
        except Exception as e:
            logger.warning(f"Failed closing database: {e}")

        # === CLOSE BOT ===
        try:
            if bot:
                await bot.close()
            logger.info("🤖 Bot shut down.")
        except Exception:
            pass

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # --- Setup signals for graceful shutdown ---
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(start_bot())
    finally:
        loop.close()
        logger.info("🔌 Graceful shutdown complete.")

if __name__ == "__main__":
    main()
