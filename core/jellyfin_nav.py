import os
import traceback
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout, Page
from config.settings import settings
from core.services.admin_notifier import AdminNotifier
from utils.logger_factory import setup_logger

logger = setup_logger(__name__)
ERROR_DIR = Path(settings.ERROR_SCREENSHOT_PATH)
ERROR_DIR.mkdir(parents=True, exist_ok=True)


class JellyfinNavigator:
    def __init__(self, jellyfin_url: str, admin_notifier: AdminNotifier):
        self.jellyfin_url = jellyfin_url.rstrip('/')
        self.admin_notifier = admin_notifier

    async def _goto_url(self, page: Page, url: str, timeout: int = 15000):
        logger.info(f"🌐 Navigating to: {url}")
        await page.goto(url, timeout=timeout)

    async def _wait_for_login_load(self, page: Page):
        try:
            logger.info("⏳ Waiting for 'Manual Login' button...")
            await page.wait_for_selector(".btnManual", timeout=10000)
            await page.click(".btnManual")
            logger.info("🖱️ Clicked Manual Login.")

            logger.info("⏳ Waiting for username field to become active...")
            await page.wait_for_selector("label.inputLabelFocused[for='txtManualName']", timeout=5000)
            logger.info("✍️ Manual login fields are active.")
        except PlaywrightTimeout:
            logger.warning("⚠️ Manual login prompt not shown — continuing anyway.")
            # optionally:
            # await self._screenshot(page, "login_prompt_missing.png")

    async def _fill_login_credentials(self, page: Page, username: str, password: str):
        logger.info("🔑 Entering credentials...")
        await page.fill('#txtManualName', username)
        await page.fill('#txtManualPassword', password)
        logger.info("🔘 Submitting login form.")
        await page.click('button:has-text("Sign In")')
        try:
            await page.wait_for_url("**/web/index.html#/home.html", timeout=10000)
            logger.info("🏠 Login success — at home page.")
        except PlaywrightTimeout:
            await self._screenshot(page, "error_post_login.png")
            logger.error("❌ Login timed out.")
            raise

    async def _handle_login_ui(self, page: Page, username: str, password: str):
        login_url = f"{self.jellyfin_url}/web/index.html#!/login.html"
        logger.info(f"🔐 Navigating to login page as {username}: {login_url}")
        await self._goto_url(page, login_url)
        # await self._wait_for_login_load(page)
        await self._fill_login_credentials(page, username, password)

    async def _navigate_to_profile(self, page: Page, user_id: str):
        profile_url = f"{self.jellyfin_url}/web/index.html#/userprofile.html?userId={user_id}"
        logger.info(f"➡️ Navigating to profile page: {profile_url}")
        await self._goto_url(page, profile_url)

    async def _upload_avatar(self, page: Page, avatar_path: str, username: str, user_id: str):
        logger.info("📸 Waiting for upload input...")
        add_image_button = await page.query_selector("#btnAddImage")
        if add_image_button and await add_image_button.is_visible():
            logger.info("📎 Clicking 'Add Image' button to reveal file input...")
            await add_image_button.click()

        await page.wait_for_selector("input#uploadImage", timeout=20000)
        filename = f"{username}_{user_id}.jpg"
        logger.info(f"📁 Uploading file: {filename}")
        await page.set_input_files("input#uploadImage", avatar_path)

        logger.info("⏳ Waiting for confirmation (Delete Image button)...")
        try:
            await page.locator("body").click()
            await page.wait_for_selector("button#btnDeleteImage:not(.hide)", timeout=10000)
            logger.info("✅ Upload confirmed — 'Delete Image' button is visible.")
        except PlaywrightTimeout:
            logger.warning("⚠️ Timeout waiting for confirmation — upload may not have succeeded.")
            await self._screenshot(page, "error_confirm_upload.png")
            await self._notify_admin("Upload Timeout", traceback.format_exc())

        # await self._screenshot(page, "debug_after_upload.png")

    async def _disable_display_playlists(self, page: Page, user_id: str):
        try:
            logger.info("👤 Opening user menu...")
            await page.click(".headerUserButton")

            logger.info("⚙️ Clicking 'Home Preferences'...")
            await page.wait_for_selector(f"a[href*='/mypreferenceshome.html?userId={user_id}']", timeout=5000)
            await page.click(f"a[href*='/mypreferenceshome.html?userId={user_id}']")

            logger.info("✅ Waiting for 'Display on home screen' checkbox...")
            await page.wait_for_selector("input.chkIncludeInMyMedia", timeout=5000)

            checkbox = page.locator("input.chkIncludeInMyMedia")
            if await checkbox.is_checked():
                logger.info("🔘 Checkbox is checked, unchecking it...")
                await page.click("span.checkboxLabel:has-text('Display on home screen')")
            else:
                logger.info("☑️ Checkbox already unchecked.")

            logger.info("💾 Clicking Save button...")
            await page.click("button.btnSave")
            await page.wait_for_timeout(1000)  # small delay to allow save

            logger.info("✅ Display on home screen disabled.")
        except Exception as e:
            await self._screenshot(page, "error_disable_display_on_home.png")
            logger.error(f"❌ Failed to disable 'Display on home screen': {e}")
            await self._notify_admin("Disable Home Display Failed", traceback.format_exc())


    async def _logout_and_verify(self, page: Page):
        logger.info("🚪 Attempting logout...")
        await page.click("button[title='Menu']")
        logger.info("📂 Sidebar opened.")
        await page.click("a[data-itemid='logout']")
        logger.info("🔒 Sign out clicked.")
        try:
            await page.wait_for_selector("form.manualLoginForm", state="visible", timeout=5000)
            logger.info("🔁 Manual login screen detected — logout confirmed.")
        except PlaywrightTimeout:
            await self._screenshot(page, "error_logout_timeout.png")
            logger.error("⚠️ Logout verification failed.")
            await self._notify_admin("Logout Timeout", traceback.format_exc())
            raise

    async def _screenshot(self, page: Page, filename: str):
        path = ERROR_DIR / filename
        await page.screenshot(path=str(path))
        logger.warning(f"📸 Saved error screenshot to {path}")

    async def _notify_admin(self, context: str, trace: str):
        if self.admin_notifier:
            await self.admin_notifier.send_admin_alert(trace, context=context)
        else:
            logger.warning("⚠️ admin_notifier not set; cannot send admin alert.")

    async def upload_avatar(self, username: str, password: str, user_id: str, avatar_path: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=None)
            page = await context.new_page()

            try:
                await self._handle_login_ui(page, username, password)
                await self._navigate_to_profile(page, user_id)
                await self._upload_avatar(page, avatar_path, username, user_id)
                # await self._disable_display_playlists(page, user_id)
                await self._logout_and_verify(page)
            except PlaywrightTimeout as e:
                await self._screenshot(page, "error_login_timeout.png")
                logger.error(f"❌ Timeout during Playwright operation: {e}")
                await self._notify_admin("Playwright Timeout", traceback.format_exc())
                raise
            except Exception as e:
                await self._screenshot(page, "error_login_exception.png")
                logger.error(f"❌ Unexpected error during upload: {e}")
                await self._notify_admin("Unhandled Playwright Error", traceback.format_exc())
                raise
            finally:
                await context.close()
                await browser.close()