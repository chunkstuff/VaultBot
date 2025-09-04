import discord
import traceback
from .modal import RegisterModal

class RegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="register_button")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

class SingleUseRegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="register_single_button")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())
        button.disabled = True
        await interaction.message.edit(view=self)

