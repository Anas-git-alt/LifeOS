"""Health check cog."""

import discord
from discord.ext import commands

from bot.utils import api_get


class HealthCog(commands.Cog, name="Health"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="status")
    async def system_status(self, ctx):
        try:
            health = await api_get("/health")
            readiness = await api_get("/readiness")
            stats = await api_get("/approvals/stats")
            embed = discord.Embed(title="LifeOS Status", color=0x16A34A)
            embed.add_field(name="Backend", value=f"{health.get('status')} v{health.get('version')}", inline=True)
            embed.add_field(name="Readiness", value=readiness.get("status", "unknown"), inline=True)
            embed.add_field(name="Bot", value=f"online ({round(self.bot.latency * 1000)}ms)", inline=True)
            embed.add_field(
                name="Approvals",
                value=f"pending={stats.get('pending', 0)} approved={stats.get('approved', 0)} rejected={stats.get('rejected', 0)}",
                inline=False,
            )
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Status check failed: {str(exc)[:200]}")

    @commands.command(name="providers")
    async def list_providers(self, ctx):
        try:
            providers = await api_get("/providers/")
            embed = discord.Embed(title="LLM Providers", color=0x2563EB)
            for provider in providers:
                embed.add_field(
                    name=provider["name"],
                    value=f"{'configured' if provider.get('available') else 'missing key'}\n{provider.get('default_model')}",
                    inline=True,
                )
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Provider check failed: {str(exc)[:200]}")


async def setup(bot):
    await bot.add_cog(HealthCog(bot))
