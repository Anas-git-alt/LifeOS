"""Agent and life workflow commands."""

import discord
from discord.ext import commands

from bot.utils import api_get, api_post, api_put

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}


class AgentsCog(commands.Cog, name="Agents"):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions: dict[tuple[int, int, int, str], int] = {}

    @staticmethod
    def _trim_error(exc: Exception, max_len: int = 220) -> str:
        return str(exc).strip()[:max_len]

    def _session_key(self, ctx, agent_name: str) -> tuple[int, int, int, str]:
        guild_id = ctx.guild.id if ctx.guild else 0
        return (guild_id, ctx.channel.id, ctx.author.id, agent_name.lower())

    def _get_active_session_id(self, ctx, agent_name: str) -> int | None:
        return self.active_sessions.get(self._session_key(ctx, agent_name))

    def _set_active_session_id(self, ctx, agent_name: str, session_id: int | None) -> None:
        key = self._session_key(ctx, agent_name)
        if session_id is None:
            self.active_sessions.pop(key, None)
            return
        self.active_sessions[key] = int(session_id)

    async def _send_agent_chat(self, agent_name: str, message: str, session_id: int | None = None) -> dict:
        payload = {"agent_name": agent_name, "message": message, "approval_policy": "auto"}
        if session_id:
            payload["session_id"] = session_id
        return await api_post("/agents/chat", payload)

    @commands.command(name="ask")
    async def ask_agent(self, ctx, agent_name: str, *, message: str):
        async with ctx.typing():
            try:
                current_session_id = self._get_active_session_id(ctx, agent_name)
                try:
                    result = await self._send_agent_chat(agent_name=agent_name, message=message, session_id=current_session_id)
                except Exception as first_error:
                    text = str(first_error).lower()
                    if current_session_id and "session" in text and "not found" in text:
                        self._set_active_session_id(ctx, agent_name, None)
                        result = await self._send_agent_chat(agent_name=agent_name, message=message, session_id=None)
                    else:
                        raise

                response = result.get("response", "No response received.")
                returned_session_id = result.get("session_id")
                if returned_session_id:
                    self._set_active_session_id(ctx, agent_name, returned_session_id)

                chunks = [response[i : i + 1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    embed = discord.Embed(title=f"{agent_name}", description=chunk, color=0x2563EB)
                    if returned_session_id:
                        title = result.get("session_title") or "New chat"
                        embed.set_footer(text=f"Session #{returned_session_id} · {title}")
                    await ctx.send(embed=embed)
                if result.get("pending_action_id"):
                    await ctx.send(f"Action #{result['pending_action_id']} requires approval (`!pending`).")
            except Exception as exc:
                await ctx.send(f"Error contacting agent: {self._trim_error(exc)}")

    @commands.command(name="sandbox")
    async def ask_sandbox(self, ctx, *, message: str):
        await ctx.invoke(self.ask_agent, agent_name="sandbox", message=message)

    @commands.command(name="sessions")
    async def list_sessions(self, ctx, agent_name: str):
        try:
            rows = await api_get(f"/agents/{agent_name}/sessions")
            if not rows:
                await ctx.send(f"No sessions found for `{agent_name}`.")
                return
            active_id = self._get_active_session_id(ctx, agent_name)
            embed = discord.Embed(title=f"Sessions · {agent_name}", color=0x2563EB)
            lines = []
            for row in rows[:20]:
                marker = "✅" if active_id and int(active_id) == int(row["id"]) else "•"
                updated = row.get("last_message_at") or row.get("updated_at") or ""
                lines.append(f"{marker} #{row['id']} · {row.get('title', 'New chat')} · {updated}")
            embed.description = "\n".join(lines)
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Failed to list sessions: {self._trim_error(exc)}")

    @commands.command(name="newsession")
    async def new_session(self, ctx, agent_name: str, *, title: str = ""):
        try:
            row = await api_post(f"/agents/{agent_name}/sessions", {"title": title or None})
            self._set_active_session_id(ctx, agent_name, int(row["id"]))
            await ctx.send(f"Created session #{row['id']} for `{agent_name}` and set it active: {row.get('title', 'New chat')}")
        except Exception as exc:
            await ctx.send(f"Failed to create session: {self._trim_error(exc)}")

    @commands.command(name="usesession")
    async def use_session(self, ctx, agent_name: str, session_id: int):
        try:
            rows = await api_get(f"/agents/{agent_name}/sessions")
            match = next((row for row in rows if int(row["id"]) == int(session_id)), None)
            if not match:
                await ctx.send(f"Session #{session_id} was not found for `{agent_name}`.")
                return
            self._set_active_session_id(ctx, agent_name, int(session_id))
            await ctx.send(f"Active session for `{agent_name}` is now #{session_id}: {match.get('title', 'New chat')}")
        except Exception as exc:
            await ctx.send(f"Failed to switch session: {self._trim_error(exc)}")

    @commands.command(name="renamesession")
    async def rename_session(self, ctx, agent_name: str, session_id: int, *, title: str):
        try:
            row = await api_put(f"/agents/{agent_name}/sessions/{session_id}", {"title": title})
            await ctx.send(f"Renamed session #{row['id']} to: {row.get('title', 'New chat')}")
        except Exception as exc:
            await ctx.send(f"Failed to rename session: {self._trim_error(exc)}")

    @commands.command(name="clearsession")
    async def clear_session(self, ctx, agent_name: str, session_id: int = 0):
        try:
            target_session_id = int(session_id) if session_id else self._get_active_session_id(ctx, agent_name)
            if not target_session_id:
                await ctx.send(f"No active session set for `{agent_name}`. Use `!sessions {agent_name}` then `!usesession`.")
                return
            row = await api_post(f"/agents/{agent_name}/sessions/{target_session_id}/clear", {})
            self._set_active_session_id(ctx, agent_name, int(row["id"]))
            await ctx.send(f"Cleared context for session #{row['id']} (`{agent_name}`).")
        except Exception as exc:
            await ctx.send(f"Failed to clear session: {self._trim_error(exc)}")

    @commands.command(name="history")
    async def session_history(self, ctx, agent_name: str, session_id: int = 0):
        try:
            target_session_id = int(session_id) if session_id else self._get_active_session_id(ctx, agent_name)
            if not target_session_id:
                await ctx.send(f"No active session set for `{agent_name}`. Use `!sessions {agent_name}` then `!usesession`.")
                return
            rows = await api_get(f"/agents/{agent_name}/sessions/{target_session_id}/messages?limit=20")
            if not rows:
                await ctx.send(f"Session #{target_session_id} has no messages yet.")
                return
            tail = rows[-10:]
            lines = []
            for row in tail:
                role = "You" if row.get("role") == "user" else agent_name
                content = (row.get("content") or "").replace("\n", " ").strip()
                content = content[:160] + ("..." if len(content) > 160 else "")
                lines.append(f"{role}: {content}")
            text = "\n".join(lines)
            chunks = [text[i : i + 1900] for i in range(0, len(text), 1900)]
            for index, chunk in enumerate(chunks):
                title = f"History · {agent_name} · #{target_session_id}"
                embed = discord.Embed(title=title if index == 0 else "History (cont.)", description=chunk, color=0x0EA5E9)
                await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Failed to fetch history: {self._trim_error(exc)}")

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
            await ctx.send(f"Error fetching agents: {self._trim_error(exc)}")

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
            await ctx.send(f"Failed to load agenda: {self._trim_error(exc)}")

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
            await ctx.send(f"Failed to load focus: {self._trim_error(exc)}")

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
            await ctx.send(f"Failed to add item: {self._trim_error(exc)}")

    @commands.command(name="done")
    async def done_item(self, ctx, item_id: int, *, note: str = ""):
        try:
            await api_post(f"/life/items/{item_id}/checkin", {"result": "done", "note": note})
            await ctx.send(f"Marked #{item_id} as done.")
        except Exception as exc:
            await ctx.send(f"Failed to mark done: {self._trim_error(exc)}")

    @commands.command(name="miss")
    async def miss_item(self, ctx, item_id: int, *, note: str = ""):
        try:
            await api_post(f"/life/items/{item_id}/checkin", {"result": "missed", "note": note})
            await ctx.send(f"Marked #{item_id} as missed.")
        except Exception as exc:
            await ctx.send(f"Failed to mark missed: {self._trim_error(exc)}")

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
            await ctx.send(f"Failed to fetch profile: {self._trim_error(exc)}")


async def setup(bot):
    await bot.add_cog(AgentsCog(bot))
