"""Agent and life workflow commands."""

import discord
from discord.ext import commands

from bot.utils import api_get, api_post, api_put

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}
VALID_ITEM_STATUSES = {"open", "done", "missed"}
NO_APPROVAL_AGENTS = {"daily-planner", "weekly-review"}
INTAKE_AGENT_NAME = "intake-inbox"


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
        approval_policy = "never" if agent_name in NO_APPROVAL_AGENTS else "auto"
        payload = {"agent_name": agent_name, "message": message, "approval_policy": approval_policy}
        if session_id:
            payload["session_id"] = session_id
        return await api_post("/agents/chat", payload)

    async def _send_capture_embed(self, ctx, result: dict, *, heading: str) -> None:
        entry = result.get("entry") or {}
        description = result.get("response", "Captured.")
        embed = discord.Embed(title=heading, description=description[:4000], color=0x7C3AED)
        if entry.get("id"):
            embed.add_field(
                name="Inbox Item",
                value=(
                    f"#{entry['id']} {entry.get('title') or 'Untitled'}\n"
                    f"{entry.get('status', 'raw')} · {entry.get('domain', 'planning')}/{entry.get('kind', 'idea')}"
                ),
                inline=False,
            )
        followups = entry.get("follow_up_questions") or []
        if followups:
            embed.add_field(
                name="Follow-up",
                value="\n".join([f"• {question}" for question in followups[:3]]),
                inline=False,
            )
        if result.get("session_id"):
            embed.set_footer(text=f"Session #{result['session_id']} · continue with !capturefollow")
        await ctx.send(embed=embed)

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
                warnings = [str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()]
                if warnings:
                    await ctx.send(f"Note: {warnings[0][:350]}")
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

    @commands.command(name="capture")
    async def capture(self, ctx, *, message: str):
        async with ctx.typing():
            try:
                result = await api_post(
                    "/life/inbox/capture",
                    {
                        "message": message,
                        "new_session": True,
                        "source": "discord_capture",
                    },
                )
                if result.get("session_id"):
                    self._set_active_session_id(ctx, INTAKE_AGENT_NAME, int(result["session_id"]))
                await self._send_capture_embed(ctx, result, heading="Inbox Capture")
            except Exception as exc:
                await ctx.send(f"Failed to capture inbox item: {self._trim_error(exc)}")

    @commands.command(name="capturefollow")
    async def capture_follow(self, ctx, *, message: str):
        session_id = self._get_active_session_id(ctx, INTAKE_AGENT_NAME)
        if not session_id:
            await ctx.send("No active capture session. Start with `!capture ...`.")
            return
        async with ctx.typing():
            try:
                result = await api_post(
                    "/life/inbox/capture",
                    {
                        "message": message,
                        "session_id": session_id,
                        "new_session": False,
                        "source": "discord_capture_followup",
                    },
                )
                await self._send_capture_embed(ctx, result, heading="Inbox Follow-up")
            except Exception as exc:
                await ctx.send(f"Failed to continue capture: {self._trim_error(exc)}")

    @commands.command(name="inbox")
    async def inbox(self, ctx, status: str = "", limit: int = 10):
        try:
            safe_limit = max(1, min(limit, 20))
            query = [f"limit={safe_limit}"]
            if status:
                query.append(f"status={status}")
            rows = await api_get(f"/life/inbox?{'&'.join(query)}")
            if not rows:
                await ctx.send("Inbox empty.")
                return
            lines = []
            for row in rows:
                lines.append(
                    f"#{row['id']} [{row.get('status')}] "
                    f"{row.get('title') or row.get('raw_text', '')[:40]} "
                    f"· {row.get('domain')}/{row.get('kind')}"
                )
            await ctx.send("Inbox:\n" + "\n".join(lines[:safe_limit]))
        except Exception as exc:
            await ctx.send(f"Failed to load inbox: {self._trim_error(exc)}")

    @commands.command(name="promotecapture")
    async def promote_capture(self, ctx, entry_id: int):
        try:
            result = await api_post(f"/life/inbox/{entry_id}/promote", {})
            life_item = result.get("life_item") or {}
            await ctx.send(
                f"Promoted inbox #{entry_id} -> life item #{life_item.get('id')}: "
                f"{life_item.get('title', 'Untitled')}"
            )
        except Exception as exc:
            await ctx.send(f"Failed to promote capture: {self._trim_error(exc)}")

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

    @commands.command(name="items")
    async def list_items(self, ctx, arg1: str = "", arg2: str = ""):
        domain = ""
        status = "open"
        for raw in [arg1, arg2]:
            token = raw.strip().lower()
            if not token:
                continue
            if token in VALID_DOMAINS and not domain:
                domain = token
                continue
            if token in VALID_ITEM_STATUSES:
                status = token
                continue
            await ctx.send(
                "Usage: `!items [domain] [status]` where domain is "
                f"{', '.join(sorted(VALID_DOMAINS))} and status is {', '.join(sorted(VALID_ITEM_STATUSES))}."
            )
            return
        try:
            params = [f"status={status}"]
            if domain:
                params.append(f"domain={domain}")
            rows = await api_get(f"/life/items?{'&'.join(params)}")
            if not rows:
                label = f"domain={domain or 'any'}, status={status}"
                await ctx.send(f"No items found ({label}).")
                return
            lines = []
            for row in rows[:20]:
                due_at = row.get("due_at")
                due_txt = f" · due {str(due_at).replace('T', ' ')[:16]} UTC" if due_at else ""
                lines.append(
                    f"#{row['id']} [{row.get('domain')}/{row.get('priority')}] "
                    f"{row.get('title')} · {row.get('status')}{due_txt}"
                )
            await ctx.send("Life items:\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to list items: {self._trim_error(exc)}")

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

    @commands.command(name="reopen")
    async def reopen_item(self, ctx, item_id: int):
        try:
            item = await api_put(f"/life/items/{item_id}", {"status": "open"})
            await ctx.send(f"Reopened #{item['id']}: {item['title']}")
        except Exception as exc:
            await ctx.send(f"Failed to reopen item: {self._trim_error(exc)}")

    @commands.command(name="goalprogress")
    async def goal_progress(self, ctx, item_id: int):
        try:
            data = await api_get(f"/life/items/{item_id}/progress")
            item = data.get("item", {})
            embed = discord.Embed(
                title=f"Goal Progress · #{item.get('id', item_id)}",
                description=item.get("title", "Life item"),
                color=0x0EA5E9,
            )
            embed.add_field(
                name="Counts",
                value=(
                    f"check-ins={data.get('checkin_count', 0)} | "
                    f"done={data.get('done_count', 0)} | "
                    f"partial={data.get('partial_count', 0)} | "
                    f"missed={data.get('missed_count', 0)}"
                ),
                inline=False,
            )
            if data.get("days_since_start") is not None:
                embed.add_field(name="Days Since Start", value=str(data["days_since_start"]), inline=True)
            checkins = data.get("checkins") or []
            if checkins:
                lines = [f"{c['result']} · {(c.get('timestamp') or '')[:16].replace('T', ' ')}" for c in checkins[:5]]
                embed.add_field(name="Recent", value="\n".join(lines), inline=False)
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Failed to fetch goal progress: {self._trim_error(exc)}")

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
