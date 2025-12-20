# core/bot/cogs/vaultplus_admin/__init__.py

async def setup(bot):
    from .admin import VaultPlusAdmin
    await bot.add_cog(VaultPlusAdmin(bot))