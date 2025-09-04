async def setup(bot):
    from .session import VaultPulse
    await bot.add_cog(VaultPulse(bot))