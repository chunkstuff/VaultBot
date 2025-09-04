async def setup(bot):
    from .commands import RegisterCommands
    from .admin import RegisterAdmin
    await bot.add_cog(RegisterCommands(bot))
    await bot.add_cog(RegisterAdmin(bot))
