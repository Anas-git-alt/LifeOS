"""Approval queue cog with owner-only decisions."""

import os

import discord
from discord.ext import commands

from bot.utils import api_get, api_post


def _owner_ids() -> set[int]:
    owners: set[int] = set()
    for raw in os.getenv("DISCORD_OWNER_IDS", "").split(","):
        raw = raw.strip()
        if raw.isdigit():
            owners.add(int(raw))
    return owners


class ApprovalsCog(commands.Cog, name="Approvals"):
    def __init__(self, bot):
        self.bot = bot
        self.owner_ids = _owner_ids()

    def _is_owner(self, user_id: int) -> bool:
        return user_id in self.owner_ids

    @commands.command(name="pending")
    async def list_pending(self, ctx):
        try:
            actions = await api_get("/approvals/")
            if not actions:
                await ctx.send("No pending approvals.")
                return
            for action in actions[:10]:
                embed = discord.Embed(
                    title=f"Pending #{action['id']}",
                    description=action.get("summary", "No summary"),
                    color=0xFFA500,
                )
                embed.add_field(name="Agent", value=action.get("agent_name", "?"), inline=True)
                embed.add_field(name="Type", value=action.get("action_type", "?"), inline=True)
                embed.add_field(name="Risk", value=action.get("risk_level", "low"), inline=True)
                embed.set_footer(text=f"!approve {action['id']} | !reject {action['id']}")
                msg = await ctx.send(embed=embed)
                await msg.add_reaction("✅")
                await msg.add_reaction("❌")
        except Exception as exc:
            await ctx.send(f"Error fetching approvals: {str(exc)[:200]}")

    @commands.command(name="approve")
    async def approve_action(self, ctx, action_id: int):
        if not self._is_owner(ctx.author.id):
            await ctx.send("Only configured owners can approve actions. Set DISCORD_OWNER_IDS in .env.")
            return
        try:
            await api_post(
                "/approvals/decide",
                {
                    "action_id": action_id,
                    "approved": True,
                    "reviewed_by": str(ctx.author),
                    "source": "discord_command",
                },
            )
            await ctx.send(f"Approved action #{action_id}.")
        except Exception as exc:
            await ctx.send(f"Error: {str(exc)[:200]}")

    @commands.command(name="reject")
    async def reject_action(self, ctx, action_id: int, *, reason: str = ""):
        if not self._is_owner(ctx.author.id):
            await ctx.send("Only configured owners can reject actions. Set DISCORD_OWNER_IDS in .env.")
            return
        try:
            await api_post(
                "/approvals/decide",
                {
                    "action_id": action_id,
                    "approved": False,
                    "reason": reason,
                    "reviewed_by": str(ctx.author),
                    "source": "discord_command",
                },
            )
            await ctx.send(f"Rejected action #{action_id}.")
        except Exception as exc:
            await ctx.send(f"Error: {str(exc)[:200]}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) not in ("✅", "❌"):
            return
        if not self._is_owner(payload.user_id):
            channel = self.bot.get_channel(payload.channel_id)
            if channel:
                await channel.send("Ignoring approval reaction from non-owner user.")
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        if not message.embeds or message.author.id != self.bot.user.id:
            return
        embed = message.embeds[0]
        if not embed.title or not embed.title.startswith("Pending #"):
            return
        try:
            action_id = int(embed.title.split("#")[1])
        except Exception:
            return

        approved = str(payload.emoji) == "✅"
        try:
            await api_post(
                "/approvals/decide",
                {
                    "action_id": action_id,
                    "approved": approved,
                    "reviewed_by": f"user:{payload.user_id}",
                    "source": "discord_reaction",
                },
            )
            await channel.send(f"{'Approved' if approved else 'Rejected'} action #{action_id}")
        except Exception as exc:
            await channel.send(f"Failed to process reaction: {str(exc)[:200]}")


async def setup(bot):
    await bot.add_cog(ApprovalsCog(bot))
