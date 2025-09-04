import discord
from discord.ui import Modal, TextInput
import random
from utils.logger_factory import setup_logger
from utils.validation import match_multiple, match_tags_from_comma_delimited

logger = setup_logger(__name__)

class WorseModal(Modal, title="Get Worse™"):
    def __init__(self, callback, collection_list, tags_list):
        super().__init__()
        self.callback_fn = callback
        self.collection_list = collection_list
        self.tags_list = tags_list

        # Get 3 random samples from the collection list, or fall back if not enough
        samples = random.sample(collection_list, k=3) if len(collection_list) >= 3 else ["Advanced", "Store", "Phallus"]

        self.num_files = TextInput(
            label="How many audio files?",
            placeholder="Leave blank for random; min files: 5; max files: 30)",
            required=False,
            max_length=3,
        )
        self.collection1 = TextInput(label="Collection 1", placeholder=f"e.g. {samples[0]}", required=False)
        self.collection2 = TextInput(label="Collection 2", placeholder=f"e.g. {samples[1]}", required=False)
        self.collection3 = TextInput(label="Collection 3", placeholder=f"e.g. {samples[2]}", required=False)
        self.tags = TextInput(
            label="Preferred Tags (comma-separated, max 3)",
            placeholder="e.g. Findom, Sir Dominic Scott, ABDL",
            required=False,
            max_length=100
        )

        self.add_item(self.num_files)
        self.add_item(self.collection1)
        self.add_item(self.collection2)
        self.add_item(self.collection3)
        self.add_item(self.tags)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
            
            # Handle number of files
            try:
                if self.num_files.value:
                    count = int(self.num_files.value)
                    if count < 5 or count > 30:
                        raise ValueError("Number must be between 5 and 30")
                else:
                    count = random.randint(5, 15)
            except ValueError:
                await interaction.followup.send("⚠️ Please enter a number between 5 and 30.", ephemeral=True)
                return
            
            # Handle collections
            collection_inputs = [self.collection1.value, self.collection2.value, self.collection3.value]
            resolved_collections = match_multiple(collection_inputs, self.collection_list)
            
            # Handle tags using the new matching function
            resolved_tags = []
            if self.tags.value:
                matched_tags, unmatched_tags = match_tags_from_comma_delimited(self.tags.value, self.tags_list, limit=3)
                # Combine both matched and unmatched for the API to handle
                resolved_tags = matched_tags + unmatched_tags

            await self.callback_fn(interaction, count, resolved_collections, resolved_tags)            
        except Exception as e:
            logger.error(f"WorseModal submission failed: {e}")
            await interaction.followup.send("❌ Something went wrong while processing your input.", ephemeral=True)

