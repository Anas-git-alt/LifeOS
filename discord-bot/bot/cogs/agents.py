"""Agent and life workflow commands."""

from datetime import datetime, timezone
import re

import discord
import httpx
from discord.ext import commands

from bot.nl import parse_commitment_prompt, parse_schedule_value
from bot.utils import api_get, api_post, api_put

VALID_DOMAINS = {"deen", "family", "work", "health", "planning"}
VALID_ITEM_STATUSES = {"open", "done", "missed"}
NO_APPROVAL_AGENTS = {"daily-planner", "weekly-review"}
INTAKE_AGENT_NAME = "intake-inbox"
COMMITMENT_SESSION_NAME = "commitment-capture"


class AgentsCog(commands.Cog, name="Agents"):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions: dict[tuple[int, int, int, str], int] = {}

    @staticmethod
    def _trim_error(exc: Exception, max_len: int = 220) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:max_len]

    @staticmethod
    def _parse_commitfollow_target(raw_message: str) -> tuple[int | None, str]:
        text = str(raw_message or "").strip()
        pattern = re.compile(r"^(?:#(\d+)|session\s+#?(\d+))\s+(.+)$", re.IGNORECASE)
        match = pattern.match(text)
        if not match:
            return None, text
        session_id = match.group(1) or match.group(2)
        return int(session_id), match.group(3).strip()

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

    @staticmethod
    def _embed_value(text: str) -> str:
        value = str(text or "none").strip() or "none"
        if len(value) <= 1024:
            return value
        return value[:1021].rstrip() + "..."

    @staticmethod
    def _clean_visible_response(text: str) -> str:
        cleaned = str(text or "Captured.").split("[INTAKE_JSON]", 1)[0].strip()
        return cleaned or "Captured."

    @staticmethod
    def _format_today_items(items: list[dict], *, include_priority: bool = False, include_reason: bool = False) -> str:
        if not items:
            return "none"
        lines = []
        for item in items[:5]:
            line = f"#{item.get('id', '?')} {item.get('title', 'Untitled')}"
            if include_priority and item.get("priority"):
                line += f" ({item['priority']})"
            if include_reason and item.get("focus_reason"):
                line += f" — {item['focus_reason']}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _format_today_scorecard(scorecard: dict | None) -> str:
        if not scorecard:
            return "none"
        sleep_hours = scorecard.get("sleep_hours")
        training_status = scorecard.get("training_status") or "unset"
        return "\n".join(
            [
                f"Sleep: {sleep_hours if sleep_hours is not None else 'unset'}h | Meals: {scorecard.get('meals_count', 0)} | Water: {scorecard.get('hydration_count', 0)}",
                f"Train: {training_status} | Protein: {'yes' if scorecard.get('protein_hit') else 'no'} | Family: {'yes' if scorecard.get('family_action_done') else 'no'}",
                f"Priorities: {scorecard.get('top_priority_completed_count', 0)} | Shutdown: {'yes' if scorecard.get('shutdown_done') else 'no'} | Rescue: {scorecard.get('rescue_status', 'unknown')}",
            ]
        )

    @staticmethod
    def _format_today_next_prayer(next_prayer: dict | None) -> str:
        if not next_prayer:
            return "none"
        starts_at = str(next_prayer.get("starts_at") or "n/a").replace("T", " ")[:16]
        ends_at = str(next_prayer.get("ends_at") or "n/a").replace("T", " ")[:16]
        return f"{next_prayer.get('name', '?')}\n{starts_at} -> {ends_at}"

    @staticmethod
    def _format_today_rescue_plan(rescue_plan: dict | None) -> str:
        if not rescue_plan:
            return "none"
        actions = rescue_plan.get("actions") or []
        return "\n".join(
            [
                f"Status: {rescue_plan.get('status', 'unknown')}",
                f"Headline: {rescue_plan.get('headline') or 'none'}",
                f"Actions: {' | '.join(actions[:3]) if actions else 'none'}",
            ]
        )

    @staticmethod
    def _format_today_sleep_protocol(sleep_protocol: dict | None) -> str:
        if not sleep_protocol:
            return "none"
        logged_bits = []
        if sleep_protocol.get("sleep_hours_logged") is not None:
            logged_bits.append(f"{sleep_protocol['sleep_hours_logged']}h")
        if sleep_protocol.get("bedtime_logged"):
            logged_bits.append(f"bed {sleep_protocol['bedtime_logged']}")
        if sleep_protocol.get("wake_time_logged"):
            logged_bits.append(f"wake {sleep_protocol['wake_time_logged']}")
        checklist = sleep_protocol.get("wind_down_checklist") or []
        return "\n".join(
            [
                f"Target: {sleep_protocol.get('bedtime_target', 'n/a')} -> {sleep_protocol.get('wake_target', 'n/a')}",
                f"Cutoff: {sleep_protocol.get('caffeine_cutoff', 'n/a')}",
                f"Logged: {' | '.join(logged_bits) if logged_bits else 'none'}",
                f"Wind-down: {'; '.join(checklist[:2]) if checklist else 'none'}",
            ]
        )

    @staticmethod
    def _format_today_streaks(streaks: list[dict]) -> str:
        if not streaks:
            return "none"
        lines = []
        for item in streaks[:7]:
            lines.append(
                f"{item.get('label', item.get('key', '?'))}: {item.get('current_streak', 0)} streak | "
                f"today {item.get('today_status', 'unknown')} | 7d {item.get('hits_last_7', 0)}/7"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_today_trend(trend_summary: dict | None) -> str:
        if not trend_summary:
            return "none"
        best_day = trend_summary.get("best_day") or {}
        recent_days = trend_summary.get("recent_days") or []
        recent_text = ", ".join(
            [f"{item.get('date')} {item.get('completion_pct', 0)}%" for item in recent_days[-3:]]
        )
        if not recent_text:
            recent_text = "none"
        best_text = "none"
        if best_day:
            best_text = f"{best_day.get('date')} ({best_day.get('completion_pct', 0)}%)"
        return "\n".join(
            [
                f"Window: {trend_summary.get('window_days', 7)} days",
                f"Average: {trend_summary.get('average_completion_pct', 0)}%",
                f"Best: {best_text}",
                f"Recent: {recent_text}",
            ]
        )

    async def _send_agent_chat(self, agent_name: str, message: str, session_id: int | None = None) -> dict:
        approval_policy = "never" if agent_name in NO_APPROVAL_AGENTS else "auto"
        payload = {"agent_name": agent_name, "message": message, "approval_policy": approval_policy}
        if session_id:
            payload["session_id"] = session_id
        return await api_post("/agents/chat", payload)

    async def _send_capture_embed(self, ctx, result: dict, *, heading: str) -> None:
        entry = result.get("entry") or {}
        description = self._clean_visible_response(result.get("response", "Captured."))
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

    async def _send_commitment_embed(self, ctx, result: dict, *, heading: str) -> None:
        entry = result.get("entry") or {}
        life_item = result.get("life_item") or {}
        follow_up_job = result.get("follow_up_job") or {}
        description = self._clean_visible_response(result.get("response", "Captured."))
        if life_item.get("id") and not result.get("needs_follow_up"):
            description = "Tracked. Reminder set. Use `!focus` to see where it ranks."
        elif result.get("session_id") and result.get("needs_follow_up"):
            description = (
                f"{description}\n\n"
                f"Reply: `!commitfollow #{result['session_id']} <answer>`"
            )
        embed = discord.Embed(title=heading, description=description[:4000], color=0x059669)
        if entry.get("id"):
            embed.add_field(
                name="Inbox",
                value=(
                    f"#{entry['id']} {entry.get('title') or 'Untitled'}\n"
                    f"{entry.get('status', 'raw')} · {entry.get('domain', 'planning')}/{entry.get('kind', 'idea')}"
                ),
                inline=False,
            )
        if life_item.get("id"):
            reminder = follow_up_job.get("next_run_at") or follow_up_job.get("run_at") or "n/a"
            embed.add_field(
                name="Tracked Commitment",
                value=(
                    f"Life item #{life_item['id']} · {life_item.get('title', 'Untitled')}\n"
                    f"Reminder: {str(reminder).replace('T', ' ')[:16]} UTC"
                ),
                inline=False,
            )
        followups = entry.get("follow_up_questions") or []
        if followups:
            embed.add_field(
                name="Need Follow-up",
                value="\n".join([f"• {question}" for question in followups[:3]]),
                inline=False,
            )
        if result.get("session_id") and result.get("needs_follow_up"):
            embed.add_field(
                name="Continue",
                value=f"`!commitfollow #{result['session_id']} <answer>`",
                inline=False,
            )
            embed.set_footer(
                text=(
                    f"Session #{result['session_id']} · copy command above"
                )
            )
        elif result.get("session_id"):
            embed.add_field(
                name="Session",
                value=f"#{result['session_id']} · new `!commit ...` starts next capture",
                inline=False,
            )
        await ctx.send(embed=embed)

    @staticmethod
    def _current_channel_payload(ctx) -> dict:
        channel_name = getattr(ctx.channel, "name", None)
        channel_id = getattr(ctx.channel, "id", None)
        return {
            "target_channel": channel_name,
            "target_channel_id": str(channel_id) if channel_id is not None else None,
        }

    @staticmethod
    def _format_focus_coach_response(result: dict, agenda: dict | None = None) -> str:
        agenda = agenda or {}
        item_lookup = {item.get("id"): item for item in agenda.get("top_focus", [])}
        primary_id = result.get("primary_item_id")
        primary = item_lookup.get(primary_id, {})
        title = primary.get("title") or (f"#{primary_id}" if primary_id is not None else "none")
        defer_labels = []
        for item_id in result.get("defer_ids", []):
            item = item_lookup.get(item_id, {})
            defer_labels.append(item.get("title") or f"#{item_id}")
        return "\n".join(
            [
                f"Primary: {title}",
                f"Why now: {result.get('why_now', 'none')}",
                f"First step: {result.get('first_step', 'none')}",
                f"Defer: {', '.join(defer_labels) if defer_labels else 'none'}",
                f"Nudge: {result.get('nudge_copy', 'none')}",
                f"Mode: {'fallback' if result.get('fallback_used') else 'ai'}",
            ]
        )

    @staticmethod
    def _format_commitment_review(result: dict) -> str:
        sections = []
        for key, label in [
            ("wins", "Wins"),
            ("stale_commitments", "Stale"),
            ("repeat_blockers", "Blockers"),
            ("promises_at_risk", "At Risk"),
            ("simplify_next_week", "Next Week"),
        ]:
            values = result.get(key) or []
            sections.append(f"{label}: {' | '.join(values[:3]) if values else 'none'}")
        sections.append(f"Mode: {'fallback' if result.get('fallback_used') else 'ai'}")
        return "\n".join(sections)

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

    @commands.command(name="commit")
    async def commit(self, ctx, *, message: str):
        parsed = parse_commitment_prompt(
            message,
            now=datetime.now(timezone.utc),
        )
        if parsed["errors"]:
            await ctx.send(parsed["errors"][0])
            return
        payload = {
            "message": parsed["data"]["message"],
            "raw_message": message,
            "new_session": True,
            "source": "discord_commitment_capture",
            "due_at": parsed["data"]["due_at"].isoformat() if parsed["data"].get("due_at") else None,
            "timezone": parsed["data"].get("timezone"),
            **self._current_channel_payload(ctx),
        }
        async with ctx.typing():
            try:
                result = await api_post("/life/commitments/capture", payload)
                if result.get("session_id") and result.get("needs_follow_up"):
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, int(result["session_id"]))
                else:
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, None)
                await self._send_commitment_embed(ctx, result, heading="Commitment Capture")
            except Exception as exc:
                await ctx.send(f"Failed to capture commitment: {self._trim_error(exc)}")

    @commands.command(name="commitfollow")
    async def commit_follow(self, ctx, *, message: str):
        explicit_session_id, cleaned_message = self._parse_commitfollow_target(message)
        session_id = explicit_session_id or self._get_active_session_id(ctx, COMMITMENT_SESSION_NAME)
        if not session_id:
            await ctx.send("No active commitment session. Use `!commit ...` or `!commitfollow #<session_id> ...`.")
            return
        parsed = parse_commitment_prompt(
            cleaned_message,
            now=datetime.now(timezone.utc),
        )
        parsed_message = parsed["data"].get("message") or cleaned_message
        due_at = parsed["data"].get("due_at") if not parsed["errors"] else None
        timezone_name = parsed["data"].get("timezone") or "Africa/Casablanca"
        async with ctx.typing():
            try:
                result = await api_post(
                    "/life/commitments/capture",
                    {
                        "message": parsed_message,
                        "raw_message": cleaned_message,
                        "session_id": session_id,
                        "new_session": False,
                        "source": "discord_commitment_followup",
                        "due_at": due_at.isoformat() if due_at else None,
                        "timezone": timezone_name,
                        **self._current_channel_payload(ctx),
                    },
                )
                if result.get("session_id") and result.get("needs_follow_up"):
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, int(result["session_id"]))
                elif self._get_active_session_id(ctx, COMMITMENT_SESSION_NAME) == session_id:
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, None)
                await self._send_commitment_embed(ctx, result, heading="Commitment Follow-up")
            except Exception as exc:
                await ctx.send(f"Failed to continue commitment capture: {self._trim_error(exc)}")

    @commands.command(name="snooze")
    async def snooze(self, ctx, item_ref: str = "", *, when: str = ""):
        item_token = str(item_ref or "").strip().lstrip("#")
        if not item_token.isdigit() or not str(when or "").strip():
            await ctx.send("Usage: `!snooze <item_id> <when>` for example `!snooze 12 in 2 hours`.")
            return
        item_id = int(item_token)
        parsed = parse_schedule_value(when, now=datetime.now(timezone.utc))
        if parsed["errors"]:
            await ctx.send(parsed["errors"][0])
            return
        if parsed["data"].get("schedule_type") != "once" or not parsed["data"].get("run_at"):
            await ctx.send("Snooze needs a one-time time like `tomorrow at 9am` or `in 2 hours`.")
            return
        try:
            item = await api_post(
                f"/life/items/{item_id}/snooze",
                {
                    "due_at": parsed["data"]["run_at"].isoformat(),
                    "timezone": "Africa/Casablanca",
                    "source": "discord",
                },
            )
            due_at = str(item.get("due_at") or "").replace("T", " ")[:16]
            await ctx.send(f"Snoozed #{item['id']} to {due_at} UTC: {item['title']}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                await ctx.send(f"No life item #{item_id}. Use `!focus` or `!items` to copy a real item id.")
                return
            await ctx.send(f"Failed to snooze item: {self._trim_error(exc)}")
        except Exception as exc:
            await ctx.send(f"Failed to snooze item: {self._trim_error(exc)}")

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
            embed.add_field(
                name="Scorecard",
                value=self._embed_value(self._format_today_scorecard(agenda.get("scorecard"))),
                inline=False,
            )
            embed.add_field(
                name="Next Prayer",
                value=self._embed_value(self._format_today_next_prayer(agenda.get("next_prayer"))),
                inline=True,
            )
            embed.add_field(
                name="Rescue Plan",
                value=self._embed_value(self._format_today_rescue_plan(agenda.get("rescue_plan"))),
                inline=False,
            )
            embed.add_field(
                name="Sleep Protocol",
                value=self._embed_value(self._format_today_sleep_protocol(agenda.get("sleep_protocol"))),
                inline=False,
            )
            embed.add_field(
                name="Streaks",
                value=self._embed_value(self._format_today_streaks(agenda.get("streaks", []))),
                inline=False,
            )
            embed.add_field(
                name="7-Day Trend",
                value=self._embed_value(self._format_today_trend(agenda.get("trend_summary"))),
                inline=False,
            )
            embed.add_field(
                name="Commitment Radar",
                value=self._embed_value(self._format_today_items(agenda.get("top_focus", []), include_priority=True, include_reason=True)),
                inline=False,
            )
            embed.add_field(
                name="Top Focus",
                value=self._embed_value(self._format_today_items(agenda.get("top_focus", []), include_priority=True)),
                inline=False,
            )
            embed.add_field(
                name="Due Today",
                value=self._embed_value(self._format_today_items(agenda.get("due_today", []))),
                inline=False,
            )
            embed.add_field(
                name="Overdue",
                value=self._embed_value(self._format_today_items(agenda.get("overdue", []))),
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
            lines = []
            for index, item in enumerate(top_focus[:3], start=1):
                lines.append(
                    f"{index}) #{item['id']} {item['title']} [{item['domain']}/{item['priority']}] — "
                    f"{item.get('focus_reason', 'focus now')}"
                )
            await ctx.send("Top 3 focus items:\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to load focus: {self._trim_error(exc)}")

    @commands.command(name="focuscoach")
    async def focus_coach(self, ctx):
        try:
            agenda = await api_get("/life/today")
            result = await api_get("/life/coach/daily-focus")
            await ctx.send(self._format_focus_coach_response(result, agenda))
        except Exception as exc:
            await ctx.send(f"Failed to load focus coach: {self._trim_error(exc)}")

    @commands.command(name="commitreview")
    async def commitment_review(self, ctx):
        try:
            result = await api_get("/life/coach/weekly-review")
            await ctx.send(self._format_commitment_review(result))
        except Exception as exc:
            await ctx.send(f"Failed to load commitment review: {self._trim_error(exc)}")

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
