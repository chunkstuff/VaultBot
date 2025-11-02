import discord
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ui import View, Button
from config.settings import settings
from .modal import WorseModal
from .playlist_api import (
    generate_playlist,
    create_playlist,
    build_playlist_url,
)
from .playlist_db import (
    log_playlist_creation,
    count_active_playlists,
    get_next_playlist_number,
    build_sequential_name,
    log_playlist_items,
)
from .playlist_utils import reconcile_deleted_playlists, expire_and_delete_old_playlists
from core.events.playlist_events import PlaylistCreateEvent
from utils.logger_factory import setup_logger
import traceback

logger = setup_logger(__name__)


class WorseView(View):
    def __init__(self, bot, collection_list, tags_list):
        super().__init__(timeout=None)
        self.bot = bot
        self.collection_list = collection_list
        self.tags_list = tags_list

    @discord.ui.button(label="🫧 Get Worse", style=discord.ButtonStyle.danger, custom_id="make_me_worse_button")
    async def worse_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(WorseModal(
            callback=self._handle_submission,
            collection_list=self.collection_list,
            tags_list=self.tags_list
        ))

    @discord.ui.button(label="📚 Available Collections", style=discord.ButtonStyle.secondary, custom_id="available_collections_button")
    async def show_collections_button(self, interaction: discord.Interaction, button: Button):
        try:
            valid_collections = [c for c in self.collection_list if c.lower() != "unknown"]
            valid_collections.sort()

            midpoint = len(valid_collections) // 2
            left_column = valid_collections[:midpoint]
            right_column = valid_collections[midpoint:]

            embed = discord.Embed(
                title="📚 Available Collections",
                description=(
                    "Use **unique or distinctive words** from these names (e.g. `Advanced`, `Store`, `Phallus`) "
                    "to guide your playlist when filling out the Make Me Worse Generator. "
                    "Full names aren't necessary, but results may vary depending on overlap (e.g. `Lull`, `Lullaby`)."
                ),
                color=discord.Color.purple()
            )
            embed.add_field(name="Collections (A–S)", value="\n".join(left_column) or "—", inline=True)
            embed.add_field(name="Collections (S–Z)", value="\n".join(right_column) or "—", inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"[show_collections_button] Failed to show collections: {e}")
            await interaction.response.send_message("❌ Failed to load collection list.", ephemeral=True)

    @discord.ui.button(label="🏷️ Available Tags", style=discord.ButtonStyle.secondary, custom_id="available_tags_button")
    async def show_tags_button(self, interaction: discord.Interaction, button: Button):
        try:
            valid_tags = [t for t in self.tags_list if t.lower() != "unknown"]
            valid_tags.sort()

            # 3 columns × 25 tags = 75 tags per page
            TAGS_PER_PAGE = 75
            TAGS_PER_COLUMN = 25
            
            # Split tags into pages
            pages = []
            for i in range(0, len(valid_tags), TAGS_PER_PAGE):
                page_tags = valid_tags[i:i + TAGS_PER_PAGE]
                pages.append(page_tags)
            
            # If there's only one page, send it directly
            if len(pages) == 1:
                embed = discord.Embed(
                    title="🏷️ Available Tags",
                    description=(
                        "Use **comma-separated tags** to filter your playlist (e.g. `Chastity, Gooner, Mind Break`). "
                        "Partial matches work too! You can mix and match up to 3 tags."
                    ),
                    color=discord.Color.blue()
                )
                
                # Split into 3 columns
                page_tags = pages[0]
                col1 = page_tags[0:TAGS_PER_COLUMN]
                col2 = page_tags[TAGS_PER_COLUMN:TAGS_PER_COLUMN*2]
                col3 = page_tags[TAGS_PER_COLUMN*2:TAGS_PER_COLUMN*3]
                
                if col1:
                    embed.add_field(name="Tags (A-)", value="\n".join(col1), inline=True)
                if col2:
                    embed.add_field(name="Tags (cont.)", value="\n".join(col2), inline=True)
                if col3:
                    embed.add_field(name="Tags (cont.)", value="\n".join(col3), inline=True)
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                # Multiple pages - create paginated view
                view = TagsPaginationView(pages)
                embed = view.create_embed(0)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"[show_tags_button] Failed to show tags: {e}")
            await interaction.response.send_message("❌ Failed to load tags list.", ephemeral=True)

    async def _handle_submission(
        self,
        interaction: discord.Interaction,
        num_files: int,
        collections: list[str],
        tags: list[str],
    ):
        user = interaction.user
        jf_id = await self._get_jellyfin_user_id(user)
        logger.info(f"[_handle_submission] Jellyfin ID for {user}: {jf_id}")

        if not jf_id:
            await self._respond_not_linked(interaction)
            return

        playlist_url = None  # keep this defined for the Forbidden branch

        try:
            # Access VaultPulseDB from bot dependency chain
            vault_db = self.bot.client.users.sessions.user_session_db

            # Housekeeping + active cap
            if vault_db:
                await expire_and_delete_old_playlists(vault_db, self.bot.client)
                await reconcile_deleted_playlists(vault_db, self.bot.client, str(user.id), jf_id)
                active = await count_active_playlists(vault_db, str(user.id))
                if active >= 3:
                    await interaction.followup.send(
                        "🚫 You already have 3 active playlists. Please delete one or wait for older ones to expire.",
                        ephemeral=True,
                    )
                    return

            # Build item list
            items = await self._generate_playlist_items(num_files, collections, tags)
            if not items:
                await interaction.followup.send("🤷 No matching audio items found.", ephemeral=True)
                return

            # Friendly sequential name uses Jellyfin username (fallback to Discord name)
            jf_username = await self._get_jellyfin_username(jf_id) or user.name

            # Create Jellyfin playlist with friendly name, get URL + name + jf playlist id
            playlist_url, playlist_name, jf_playlist_id = await self._create_playlist_and_get_url(
                jf_id,
                items,
                vault_db=vault_db,
                discord_id=str(user.id),
                display_name=jf_username,
            )

            # Log to VaultPulse (row + normalized items)
            if vault_db:
                user_playlist_id = await log_playlist_creation(
                    vault_db,
                    discord_id=str(user.id),
                    playlist_name=playlist_name,
                    items=items,
                    collections=collections,
                    tags=tags,
                )
                await log_playlist_items(
                    vault_db,
                    user_playlist_id=user_playlist_id,
                    jf_playlist_id=jf_playlist_id,
                    items=items,
                )
                
                jf_username = await self._get_jellyfin_username(jf_id) or user.name
                create_event = PlaylistCreateEvent(
                    discord_user_id=str(user.id),
                    discord_username=user.display_name,
                    jellyfin_user_id=jf_id,
                    playlist_name=playlist_name,
                    playlist_id=jf_playlist_id,
                    user_playlist_id=user_playlist_id,
                    num_files=len(items),
                    collections=collections,
                    tags=tags,
                    created_at=datetime.now(ZoneInfo("Europe/London")),
                )
                
                self.bot.dispatch('playlist_create', create_event)
                logger.info(f"[WorseView] Emitted playlist_create event for {user.display_name}")

            # DM + confirm
            await self._send_playlist_dm(user, playlist_url)
            await interaction.followup.send("✅ Playlist sent in DM!", ephemeral=True)

        except discord.Forbidden:
            logger.warning(f"[_send_playlist_dm] Forbidden: Unable to DM user {user} — likely due to privacy settings.")
            fallback = playlist_url or "your Vault+ account"
            await interaction.followup.send(
                f"❌ Couldn't DM you; check your privacy settings. Your playlist is available at {fallback}.",
                ephemeral=True
            )

        except discord.NotFound:
            logger.warning(f'Interaction expired for {user.display_name} - assuming playlist creation success.')
            await interaction.followup.send("✅ Playlist sent in DM!", ephemeral=True)

        except Exception as e:
            logger.error(f"[_handle_submission] Unexpected error: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("❌ Something went wrong while creating your playlist.", ephemeral=True)


    async def _get_jellyfin_user_id(self, user: discord.User | discord.Member) -> str | None:
        return await self.bot.link_map.get_jellyfin_user_id(str(user.id))
        
    async def _get_jellyfin_username(self, jf_user_id) -> str | None:
        info = await self.bot.link_map.get_discord_info(jf_user_id)
        if info and len(info) >= 2 and info[1]:
            return info[1]
        return None

    async def _respond_not_linked(self, interaction: discord.Interaction):
        await interaction.followup.send(
            "❌ No linked Vault+ account found. Please visit <#1376142045621784606> to create an account.\n"
            "If you already have a Vault+ account, please use your **Vault+ username** to link accounts.",
            ephemeral=True
        )

    async def _generate_playlist_items(self, num_files: int, collections: list[str], tags: list[str]):
        logger.info(f"[_generate_playlist_items] Generating playlist with count={num_files}, collections={collections}, tags={tags}")
        return await generate_playlist(
            jellyfin_client=self.bot.client,
            count=num_files,
            collections=collections,
            tags=tags
        )

    async def _create_playlist_and_get_url(
        self,
        jf_id: str,
        items: list,
        *,
        vault_db,
        discord_id: str,
        display_name: str,
    ) -> tuple[str, str, str]:
        """
        Creates Jellyfin playlist using a friendly sequential name.
        Returns (playlist_url, playlist_name, jellyfin_playlist_id).
        """
        # figure out next sequence number
        n = await get_next_playlist_number(vault_db, discord_id)
        playlist_name = build_sequential_name(display_name, n)

        # create on Jellyfin with this name
        jf_playlist_id, playlist_name = await create_playlist(
            jellyfin_client=self.bot.client,
            user_id=jf_id,
            items=items,
            name=playlist_name,
        )
        return build_playlist_url(jf_playlist_id), playlist_name, jf_playlist_id


    async def _send_playlist_dm(self, user: discord.User, playlist_url: str):
        await user.send(f"<:sirbubbles:1267167900159053876> Your **Get Worse** playlist is ready: {playlist_url}")


class TagsPaginationView(discord.ui.View):
    def __init__(self, pages: list[list[str]]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.pages = pages
        self.current_page = 0
        self.tags_per_column = 25
        self.update_buttons()
    
    def create_embed(self, page_index: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"🏷️ Available Tags (Page {page_index + 1}/{len(self.pages)})",
            description=(
                "Use **comma-separated tags** to filter your playlist (e.g. `Chastity, Gooner, Mind Break`). "
                "Partial matches work too! You can mix and match up to 3 tags."
            ),
            color=discord.Color.blue()
        )
        
        # Split page tags into 3 columns of 25
        page_tags = self.pages[page_index]
        col1 = page_tags[0:self.tags_per_column]
        col2 = page_tags[self.tags_per_column:self.tags_per_column*2]
        col3 = page_tags[self.tags_per_column*2:self.tags_per_column*3]
        
        if col1:
            embed.add_field(name="", value="\n".join(col1), inline=True)
        if col2:
            embed.add_field(name="", value="\n".join(col2), inline=True)
        if col3:
            embed.add_field(name="", value="\n".join(col3), inline=True)
        
        return embed
    
    def update_buttons(self):
        self.previous_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == len(self.pages) - 1)
    
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        embed = self.create_embed(self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        embed = self.create_embed(self.current_page)
        await interaction.response.edit_message(embed=embed, view=self)