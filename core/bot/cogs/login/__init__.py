# core/bot/cogs/login/__init__.py

async def setup(bot):
    from .login import LoginAdmin
    await bot.add_cog(LoginAdmin(bot))
