# core/bot/cogs/subscription_tracker/__init__.py

async def setup(bot):
    from .tracker import ExpiredSubscriptionDisabler
    await bot.add_cog(ExpiredSubscriptionDisabler(bot))