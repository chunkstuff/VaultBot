import discord

class LoginButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Login to The Vault+",
            url="https://members.thevault.locker",
            style=discord.ButtonStyle.danger  # Red button
        ))