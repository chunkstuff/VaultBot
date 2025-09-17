# core/bot/cogs/subscription_tracker/__init__.py

async def setup(bot):
    from .tracker import SubscriptionTracker
    await bot.add_cog(SubscriptionTracker(bot))