"""Agent and life workflow commands."""

import discord
from discord.ext import commands

from bot.utils import api_get, api_post

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}


class AgentsCog(commands.Cog, name="Agents"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ask")
    async def ask_agent(self, ctx, agent_name: str, *, message: str):
        async with ctx.typing():
            try:
                result = await api_post(
                    "/agents/chat",
                    {"agent_name": agent_name, "message": message, "approval_policy": "auto"},
                )
                response = result.get("response", "No response received.")
                chunks = [response[i : i + 1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    embed = discord.Embed(title=f"{agent_name}", description=chunk, color=0x2563EB)
                    await ctx.send(embed=embed)
                if result.get("pending_action_id"):
                    await ctx.send(f"Action #{result['pending_action_id']} requires approval (`!pending`).")
            except Exception as exc:
                await ctx.send(f"Error contacting agent: {str(exc)[:200]}")

    @commands.command(name="agents")
    async def list_agents(self, ctx):
        try:
            agents = await api_get("/agents/")
            embed = discord.Embed(title="LifeOS Agents", color=0x2563EB)
            for agent in agents:
                status = "ON" if agent.get("enabled") else "OFF"
                embed.add_field(
                    name=f"{agent['name']} ({status})",
                    value=f"{agent.get('description', '')[:100]}\n{agent.get('provider')} / {agent.get('model')}",
                    inline=False,
                )
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Error fetching agents: {str(exc)[:200]}")

    @commands.command(name="daily")
    async def daily_plan(self, ctx):
        await ctx.invoke(
            self.ask_agent,
            agent_name="daily-planner",
            message="Give me my morning briefing for today with prayer-aware and shift-aware blocks.",
        )

    @commands.command(name="weekly")
    async def weekly_review(self, ctx):
        await ctx.invoke(
            self.ask_agent,
            agent_name="weekly-review",
            message="Generate a weekly review covering deen, family, work, health, and planning.",
        )

    @commands.command(name="today")
    async def today(self, ctx):
        try:
            agenda = await api_get("/life/today")
            embed = discord.Embed(
                title=f"Today ({agenda.get('timezone', 'UTC')})",
                description=f"Now: {agenda.get('now')}",
                color=0x059669,
            )
            top_focus = agenda.get("top_focus", [])
            if top_focus:
                embed.add_field(
                    name="Top Focus",
                    value="\n".join([f"#{item['id']} {item['title']} ({item['priority']})" for item in top_focus]),
                    inline=False,
                )
            due_today = agenda.get("due_today", [])
            if due_today:
                embed.add_field(
                    name="Due Today",
                    value="\n".join([f"#{item['id']} {item['title']}" for item in due_today[:5]]),
                    inline=False,
                )
            overdue = agenda.get("overdue", [])
            if overdue:
                embed.add_field(
                    name="Overdue",
                    value="\n".join([f"#{item['id']} {item['title']}" for item in overdue[:5]]),
                    inline=False,
                )
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Failed to load agenda: {str(exc)[:200]}")

    @commands.command(name="focus")
    async def focus(self, ctx):
        try:
            agenda = await api_get("/life/today")
            top_focus = agenda.get("top_focus", [])
            if not top_focus:
                await ctx.send("No open focus items yet. Use `!add` to create one.")
                return
            lines = [f"1) #{item['id']} {item['title']} [{item['domain']}/{item['priority']}]" for item in top_focus]
            await ctx.send("Top 3 focus items:\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to load focus: {str(exc)[:200]}")

    @commands.command(name="add")
    async def add_item(self, ctx, domain: str, *, text: str):
        domain = domain.lower().strip()
        if domain not in VALID_DOMAINS:
            await ctx.send(f"Invalid domain '{domain}'. Use one of: {', '.join(sorted(VALID_DOMAINS))}.")
            return
        try:
            item = await api_post("/life/items", {"domain": domain, "title": text, "kind": "task"})
            await ctx.send(f"Added item #{item['id']} in {domain}: {item['title']}")
        except Exception as exc:
            await ctx.send(f"Failed to add item: {str(exc)[:200]}")

    @commands.command(name="done")
    async def done_item(self, ctx, item_id: int, *, note: str = ""):
        try:
            await api_post(f"/life/items/{item_id}/checkin", {"result": "done", "note": note})
            await ctx.send(f"Marked #{item_id} as done.")
        except Exception as exc:
            await ctx.send(f"Failed to mark done: {str(exc)[:200]}")

    @commands.command(name="miss")
    async def miss_item(self, ctx, item_id: int, *, note: str = ""):
        try:
            await api_post(f"/life/items/{item_id}/checkin", {"result": "missed", "note": note})
            await ctx.send(f"Marked #{item_id} as missed.")
        except Exception as exc:
            await ctx.send(f"Failed to mark missed: {str(exc)[:200]}")

    @commands.command(name="profile")
    async def profile(self, ctx):
        try:
            profile = await api_get("/profile/")
            await ctx.send(
                "Profile: "
                f"timezone={profile.get('timezone')} | "
                f"location={profile.get('city')}, {profile.get('country')} | "
                f"shift={profile.get('work_shift_start')}-{profile.get('work_shift_end')} | "
                f"quiet={profile.get('quiet_hours_start')}-{profile.get('quiet_hours_end')} | "
                f"nudge={profile.get('nudge_mode')}"
            )
        except Exception as exc:
            await ctx.send(f"Failed to fetch profile: {str(exc)[:200]}")


async def setup(bot):
    await bot.add_cog(AgentsCog(bot))
