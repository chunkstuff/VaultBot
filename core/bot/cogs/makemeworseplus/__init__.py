# core/bot/cogs/makemeworseplus/__init__.py

async def setup(bot):
    from .worseplus import MakeMeWorsePlus
    from .listeners import PlaylistListeners
    await bot.add_cog(MakeMeWorsePlus(bot))
    await bot.add_cog(PlaylistListeners(bot))