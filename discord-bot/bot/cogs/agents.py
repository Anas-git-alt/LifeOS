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
        self.pending_daily_log_actions: dict[int, dict] = {}

    @staticmethod
    def _trim_error(exc: Exception, max_len: int = 220) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        return text[:max_len]

    @staticmethod
    def _parse_commitfollow_target(raw_message: str) -> tuple[int | None, str, bool]:
        text = str(raw_message or "").strip()
        pattern = re.compile(r"^(?:#(\d+)|session\s+#?(\d+)|(\d+))\s+(.+)$", re.IGNORECASE)
        match = pattern.match(text)
        if not match:
            return None, text, False
        target_id = match.group(1) or match.group(2) or match.group(3)
        force_session = bool(match.group(2))
        return int(target_id), match.group(4).strip(), force_session

    def _session_key(self, ctx, agent_name: str) -> tuple[int, int, int, str]:
        guild_id = ctx.guild.id if ctx.guild else 0
        return (guild_id, ctx.channel.id, ctx.author.id, agent_name.lower())

    @staticmethod
    def _session_key_from_ids(guild_id: int | None, channel_id: int | None, author_id: int | None, agent_name: str) -> tuple[int, int, int, str]:
        return (int(guild_id or 0), int(channel_id or 0), int(author_id or 0), agent_name.lower())

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
        cleaned = str(text or "Captured.").split("[INTAKE_JSON]", 1)[0].split("[RAW_LIFE_SYNTHESIS_JSON]", 1)[0].strip()
        return cleaned or "Captured."

    @staticmethod
    def _split_discord_chunks(text: str, limit: int = 1800) -> list[str]:
        remaining = str(text or "").strip()
        if not remaining:
            return ["No response received."]
        chunks: list[str] = []
        while len(remaining) > limit:
            split_at = max(
                remaining.rfind("\n\n", 0, limit),
                remaining.rfind("\n", 0, limit),
                remaining.rfind(". ", 0, limit),
                remaining.rfind(" ", 0, limit),
            )
            if split_at < max(400, limit // 3):
                split_at = limit
            chunk = remaining[:split_at].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[split_at:].strip()
        if remaining:
            chunks.append(remaining)
        return chunks or ["No response received."]

    @staticmethod
    def _format_today_items(items: list[dict], *, include_priority: bool = False, include_reason: bool = False) -> str:
        if not items:
            return "none"
        lines = []
        for item in items[:5]:
            line = f"#{item.get('id', '?')} {item.get('title', 'Untitled')}"
            if include_priority and item.get("priority"):
                line += f" ({item['priority']})"
            reason = item.get("focus_reason") or item.get("priority_reason")
            if include_reason and reason:
                line += f" — {reason}"
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

    async def _send_agent_chat(
        self,
        agent_name: str,
        message: str,
        session_id: int | None = None,
        transient_system_note: str | None = None,
    ) -> dict:
        approval_policy = "never" if agent_name in NO_APPROVAL_AGENTS else "auto"
        payload = {"agent_name": agent_name, "message": message, "approval_policy": approval_policy}
        if session_id:
            payload["session_id"] = session_id
        if transient_system_note:
            payload["transient_system_note"] = transient_system_note
        return await api_post("/agents/chat", payload)

    async def _send_agent_result(
        self,
        destination,
        agent_name: str,
        result: dict,
        *,
        ctx=None,
        original_message: str | None = None,
        guild_id: int | None = None,
        channel_id: int | None = None,
        author_id: int | None = None,
    ) -> None:
        response = result.get("response", "No response received.")
        returned_session_id = result.get("session_id")
        if ctx is not None:
            guild_id = ctx.guild.id if ctx.guild else 0
            channel_id = ctx.channel.id
            author_id = ctx.author.id
            if returned_session_id:
                self._set_active_session_id(ctx, agent_name, returned_session_id)
        elif returned_session_id:
            self.active_sessions[self._session_key_from_ids(guild_id, channel_id, author_id, agent_name)] = int(returned_session_id)

        chunks = self._split_discord_chunks(response)
        first_sent = None
        for index, chunk in enumerate(chunks, start=1):
            embed = discord.Embed(title=f"{agent_name}", description=chunk, color=0x2563EB)
            if returned_session_id:
                title = result.get("session_title") or "New chat"
                suffix = f" · part {index}/{len(chunks)}" if len(chunks) > 1 else ""
                embed.set_footer(text=f"Session #{returned_session_id} · {title}{suffix}")
            sent = await destination.send(embed=embed)
            if index == 1:
                first_sent = sent

        pending_action_id = result.get("pending_action_id")
        pending_action_type = result.get("pending_action_type")
        if pending_action_id and pending_action_type == "daily_log_batch" and first_sent is not None:
            try:
                self.pending_daily_log_actions[int(first_sent.id)] = {
                    "action_id": int(pending_action_id),
                    "agent_name": agent_name,
                    "session_id": int(returned_session_id) if returned_session_id else None,
                    "guild_id": int(guild_id or 0),
                    "channel_id": int(channel_id or 0),
                    "author_id": int(author_id or 0),
                    "followup_request": self._extract_followup_request(original_message or ""),
                }
                await first_sent.add_reaction("✅")
            except Exception:
                await destination.send(f"Daily log proposal #{pending_action_id} needs approval (`!approve {pending_action_id}`).")
        elif pending_action_id:
            await destination.send(f"Action #{pending_action_id} requires approval (`!pending`).")

        warnings = [str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()]
        if warnings:
            await destination.send(f"Note: {warnings[0][:350]}")

    async def _resolve_commitment_session_from_inbox(self, inbox_id: int) -> tuple[int | None, str | None, bool]:
        try:
            entry = await api_get(f"/life/inbox/{inbox_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None, None, False
            raise
        source_agent = entry.get("source_agent") or "unknown"
        session_id = entry.get("source_session_id")
        if source_agent != COMMITMENT_SESSION_NAME or not session_id:
            return (
                None,
                f"Inbox #{inbox_id} is from `{source_agent}`, not commitment capture. "
                "Use the Inbox id shown under a `!commit` message, or `!commitfollow session #<session_id> <answer>`.",
                True,
            )
        return int(session_id), None, True

    async def _resolve_recent_capture_session(self) -> tuple[int | None, str | None]:
        try:
            rows = await api_get("/life/inbox?status=clarifying&limit=5")
        except Exception:
            return None, None
        for row in rows or []:
            source_agent = str(row.get("source_agent") or "").strip()
            session_id = row.get("source_session_id")
            if source_agent in {COMMITMENT_SESSION_NAME, INTAKE_AGENT_NAME} and session_id:
                route_hint = "commitment" if source_agent == COMMITMENT_SESSION_NAME else "intake"
                return int(session_id), route_hint
        return None, None

    @staticmethod
    def _extract_followup_request(message: str) -> str | None:
        text = str(message or "").strip()
        mixed_action = re.search(
            r"\b(?:log(?:ged)?\s+(?:it|them|this)?|apply\s+(?:it|them|this)?|save\s+(?:it|them|this)?)\b"
            r"(?P<rest>.*?\b(?:create|add|make|track|remind|task|tasks|reminder|reminders)\b.+)$",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if mixed_action:
            rest = re.sub(r"^\s*(?:,|and|then|plus|also)\s+", "", mixed_action.group("rest").strip(), flags=re.IGNORECASE)
            rest = re.sub(r"\bweding\b", "wedding", rest, flags=re.IGNORECASE)
            return rest[:500] if rest else None
        if "?" not in text:
            return None
        question = text.split("?", 1)[0].strip()
        if not question:
            return None
        return f"{question}?"

    async def _send_capture_embed(self, ctx, result: dict, *, heading: str) -> None:
        entry = result.get("entry") or {}
        entries = result.get("entries") or ([entry] if entry else [])
        logged_signals = result.get("logged_signals") or []
        completed_items = result.get("completed_items") or []
        life_items = result.get("life_items") or []
        if result.get("life_item") and not life_items:
            life_items = [result["life_item"]]
        wiki_proposals = result.get("wiki_proposals") or []
        clarifying_count = len([item for item in entries if item.get("status") == "clarifying"])
        if logged_signals or completed_items:
            description_parts = ["Updated Today."]
            if completed_items:
                description_parts.append(f"Completed {len(completed_items)} item(s).")
            if logged_signals:
                description_parts.append(f"Logged: {', '.join(logged_signals)}.")
            description = " ".join(description_parts)
        elif entries or life_items or wiki_proposals:
            description_parts = [f"Captured via {result.get('route', 'capture')}."]
            if life_items:
                description_parts.append(f"Tracked {len(life_items)} item(s).")
            if clarifying_count:
                description_parts.append(f"{clarifying_count} need answer.")
            if wiki_proposals:
                description_parts.append(f"{len(wiki_proposals)} memory review item(s).")
            description = " ".join(description_parts)
        else:
            description = self._clean_visible_response(result.get("response", "Captured."))
        embed = discord.Embed(title=heading, description=description[:4000], color=0x2563EB)
        if completed_items:
            lines = [
                f"#{item['id']} {item.get('title', 'Untitled')} · {item.get('status', 'done')}"
                for item in completed_items[:5]
            ]
            embed.add_field(name="Completed", value=self._embed_value("\n".join(lines)), inline=False)
        if logged_signals:
            embed.add_field(name="Logged", value=self._embed_value(", ".join(logged_signals)), inline=False)
        if entry.get("id"):
            priority = entry.get("promotion_payload") or {}
            embed.add_field(
                name="Capture Item",
                value=self._embed_value(
                    f"#{entry['id']} {entry.get('title') or 'Untitled'}\n"
                    f"{entry.get('status', 'raw')} · {entry.get('domain', 'planning')}/{entry.get('kind', 'idea')}\n"
                    f"AI priority {priority.get('priority_score', '?')}/100 · {priority.get('priority_reason', 'reason pending')}"
                ),
                inline=False,
            )
        if life_items:
            lines = [
                f"#{item['id']} {item.get('title', 'Untitled')} · {item.get('priority', 'medium')} ({item.get('priority_score', 50)}/100)"
                for item in life_items[:5]
            ]
            embed.add_field(name="Tracked", value=self._embed_value("\n".join(lines)), inline=False)
        if wiki_proposals:
            embed.add_field(name="Memory Review", value=f"{len(wiki_proposals)} review-required item(s)", inline=False)
        followups = entry.get("follow_up_questions") or []
        if followups:
            embed.add_field(
                name="Needs Answer",
                value=self._embed_value("\n".join([f"• {question}" for question in followups[:3]])),
                inline=False,
            )
        if result.get("session_id"):
            embed.set_footer(text=f"Session #{result['session_id']} · continue with !capturefollow session #{result['session_id']} <answer>")
        await ctx.send(embed=embed)

    async def _send_commitment_embed(self, ctx, result: dict, *, heading: str) -> None:
        entry = result.get("entry") or {}
        life_item = result.get("life_item") or next(iter(result.get("life_items") or []), {})
        follow_up_job = result.get("follow_up_job") or {}
        description = self._clean_visible_response(result.get("response", "Captured."))
        if life_item.get("id") and not result.get("needs_follow_up"):
            description = "Tracked. Reminder set. Use `!focus` to see where it ranks."
        elif result.get("session_id") and result.get("needs_follow_up"):
            if entry.get("id"):
                reply_hint = f"!commitfollow {entry['id']} <answer>"
            else:
                reply_hint = f"!commitfollow session #{result['session_id']} <answer>"
            description = (
                f"{description}\n\n"
                f"Reply: `{reply_hint}`"
            )
        embed = discord.Embed(title=heading, description=description[:4000], color=0x059669)
        if entry.get("id"):
            embed.add_field(
                name="Capture Item",
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
            inbox_hint = f"`!commitfollow {entry['id']} <answer>`" if entry.get("id") else ""
            session_hint = f"`!commitfollow session #{result['session_id']} <answer>`"
            embed.add_field(
                name="Continue",
                value=" or ".join([part for part in [inbox_hint, session_hint] if part]),
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

                await self._send_agent_result(
                    result=result,
                    destination=ctx,
                    agent_name=agent_name,
                    ctx=ctx,
                    original_message=message,
                )
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
                    "/life/capture",
                    {
                        "message": message,
                        "new_session": True,
                        "source": "discord_capture",
                    },
                )
                route = result.get("route")
                if result.get("session_id") and route == "intake":
                    self._set_active_session_id(ctx, INTAKE_AGENT_NAME, int(result["session_id"]))
                if result.get("session_id") and route == "commitment" and result.get("needs_follow_up"):
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, int(result["session_id"]))
                await self._send_capture_embed(ctx, result, heading="Capture")
            except Exception as exc:
                await ctx.send(f"Failed to capture: {self._trim_error(exc)}")

    @commands.command(name="meeting")
    async def meeting(self, ctx, *, summary: str):
        async with ctx.typing():
            try:
                result = await api_post(
                    "/life/capture",
                    {
                        "message": summary,
                        "source": "discord_meeting",
                        "route_hint": "memory",
                    },
                )
                event = result.get("event") or {}
                proposals = result.get("wiki_proposals") or []
                embed = discord.Embed(
                    title="Memory Review",
                    description=f"Captured context event #{event.get('id', '?')}.",
                    color=0x7C3AED,
                )
                embed.add_field(name="Domain", value=event.get("domain", "planning"), inline=True)
                embed.add_field(name="Memory Review", value=str(len(proposals)), inline=True)
                if result.get("entries"):
                    embed.add_field(
                        name="Action Capture",
                        value=", ".join(f"#{item['id']}" for item in result["entries"][:5]),
                        inline=False,
                    )
                await ctx.send(embed=embed)
            except Exception as exc:
                await ctx.send(f"Failed to capture meeting summary: {self._trim_error(exc)}")

    @commands.Cog.listener("on_message")
    async def capture_notification_reply(self, message):
        author = getattr(message, "author", None)
        author_id = getattr(author, "id", None)
        bot_user_id = getattr(getattr(self.bot, "user", None), "id", None)
        if bot_user_id is not None and author_id == bot_user_id:
            return
        content = str(getattr(message, "content", "") or "").strip()
        if not content or content.startswith("!"):
            return
        reference = getattr(message, "reference", None)
        notification_message_id = getattr(reference, "message_id", None)
        if not notification_message_id:
            return
        pending_log = self.pending_daily_log_actions.get(int(notification_message_id))
        if pending_log:
            if int(author_id or 0) != int(pending_log.get("author_id") or 0):
                return
            self.pending_daily_log_actions.pop(int(notification_message_id), None)
            try:
                await api_post(
                    "/approvals/decide",
                    {
                        "action_id": pending_log["action_id"],
                        "approved": False,
                        "reason": f"Replaced by Discord correction: {content[:200]}",
                        "reviewed_by": str(author_id or ""),
                        "source": "discord_daily_log_correction",
                    },
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
            result = await self._send_agent_chat(
                agent_name=pending_log.get("agent_name") or "sandbox",
                message=content,
                session_id=pending_log.get("session_id"),
            )
            await self._send_agent_result(
                destination=message.channel,
                agent_name=pending_log.get("agent_name") or "sandbox",
                result=result,
                guild_id=pending_log.get("guild_id"),
                channel_id=pending_log.get("channel_id"),
                author_id=pending_log.get("author_id"),
            )
            return
        try:
            await api_post(
                "/memory/intake/job-reply",
                {
                    "notification_message_id": str(notification_message_id),
                    "reply_text": content,
                    "discord_channel_id": str(getattr(message.channel, "id", "")),
                    "discord_reply_message_id": str(getattr(message, "id", "")),
                    "discord_user_id": str(getattr(message.author, "id", "")),
                    "source": "discord_reply",
                },
            )
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return
            raise

    @commands.Cog.listener("on_raw_reaction_add")
    async def approve_daily_log_reaction(self, payload):
        if str(getattr(payload, "emoji", "")) != "✅":
            return
        user_id = int(getattr(payload, "user_id", 0) or 0)
        bot_user_id = getattr(getattr(self.bot, "user", None), "id", None)
        if bot_user_id is not None and user_id == int(bot_user_id):
            return
        message_id = int(getattr(payload, "message_id", 0) or 0)
        pending_log = self.pending_daily_log_actions.get(message_id)
        if not pending_log:
            return
        if user_id != int(pending_log.get("author_id") or 0):
            return
        self.pending_daily_log_actions.pop(message_id, None)
        try:
            result = await api_post(
                "/approvals/decide",
                {
                    "action_id": pending_log["action_id"],
                    "approved": True,
                    "reviewed_by": str(user_id),
                    "source": "discord_reaction",
                },
            )
        except Exception:
            return
        channel_id = int(getattr(payload, "channel_id", 0) or pending_log.get("channel_id") or 0)
        channel = None
        get_channel = getattr(self.bot, "get_channel", None)
        if callable(get_channel):
            channel = get_channel(channel_id)
        if channel is None:
            fetch_channel = getattr(self.bot, "fetch_channel", None)
            if callable(fetch_channel):
                try:
                    channel = await fetch_channel(channel_id)
                except Exception:
                    channel = None
        if channel is not None:
            status = result.get("status") or "approved"
            detail = result.get("result") or result.get("message") or "Logged."
            await channel.send(f"Daily log {status}: {detail[:500]}")
            followup_request = pending_log.get("followup_request")
            if followup_request and str(status).lower() in {"approved", "executed"}:
                try:
                    transient_note = (
                        "A daily log approval was just executed and Today state is current. "
                        "Do not ask to confirm that log again. "
                        "Answer the remaining user question now."
                    )
                    followup = await self._send_agent_chat(
                        agent_name=pending_log.get("agent_name") or "sandbox",
                        message=followup_request,
                        session_id=pending_log.get("session_id"),
                        transient_system_note=transient_note,
                    )
                    await self._send_agent_result(
                        destination=channel,
                        agent_name=pending_log.get("agent_name") or "sandbox",
                        result=followup,
                        guild_id=pending_log.get("guild_id"),
                        channel_id=pending_log.get("channel_id"),
                        author_id=pending_log.get("author_id"),
                    )
                except Exception:
                    await channel.send("Daily log applied, but I could not continue the follow-up answer.")

    @commands.command(name="capturefollow")
    async def capture_follow(self, ctx, *, message: str):
        explicit_session_id, cleaned_message, _force_session = self._parse_commitfollow_target(message)
        session_id = self._get_active_session_id(ctx, COMMITMENT_SESSION_NAME)
        route_hint = "commitment"
        if not session_id:
            session_id = self._get_active_session_id(ctx, INTAKE_AGENT_NAME)
            route_hint = "intake"
        if explicit_session_id is not None:
            session_id = explicit_session_id
            message = cleaned_message
            route_hint = "commitment"
        if not session_id:
            session_id, resolved_route = await self._resolve_recent_capture_session()
            if session_id and resolved_route:
                route_hint = resolved_route
        if not session_id:
            await ctx.send("No active capture session. Use `!capture ...` or `!capturefollow session #<session_id> <answer>`.")
            return
        async with ctx.typing():
            try:
                result = await api_post(
                    "/life/capture",
                    {
                        "message": message,
                        "session_id": session_id,
                        "new_session": False,
                        "source": "discord_capture_followup",
                        "route_hint": route_hint,
                    },
                )
                if result.get("session_id"):
                    agent_name = COMMITMENT_SESSION_NAME if route_hint == "commitment" else INTAKE_AGENT_NAME
                    self._set_active_session_id(ctx, agent_name, int(result["session_id"]))
                await self._send_capture_embed(ctx, result, heading="Capture Follow-up")
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
                result = await api_post("/life/capture", {**payload, "route_hint": "commitment"})
                if result.get("session_id") and result.get("needs_follow_up"):
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, int(result["session_id"]))
                else:
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, None)
                await self._send_commitment_embed(ctx, result, heading="Commitment Capture")
            except Exception as exc:
                await ctx.send(f"Failed to capture commitment: {self._trim_error(exc)}")

    @commands.command(name="commitfollow")
    async def commit_follow(self, ctx, *, message: str):
        explicit_target_id, cleaned_message, force_session = self._parse_commitfollow_target(message)
        session_id = self._get_active_session_id(ctx, COMMITMENT_SESSION_NAME)
        if explicit_target_id is not None:
            if force_session:
                session_id = explicit_target_id
            else:
                resolved_session_id, resolve_error, found_inbox = await self._resolve_commitment_session_from_inbox(explicit_target_id)
                if resolve_error:
                    await ctx.send(resolve_error)
                    return
                session_id = resolved_session_id or explicit_target_id
                if found_inbox and resolved_session_id:
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, resolved_session_id)
        if not session_id:
            await ctx.send("No active commitment session. Use `!commit ...`, `!commitfollow <inbox_id> ...`, or `!commitfollow session #<session_id> ...`.")
            return
        parsed = parse_commitment_prompt(
            cleaned_message,
            now=datetime.now(timezone.utc),
        )
        parsed_message = parsed["data"].get("message") or cleaned_message
        due_at = parsed["data"].get("due_at") if not parsed["errors"] else None
        timezone_name = parsed["data"].get("timezone") or "Africa/Casablanca"
        payload = {
            "message": parsed_message,
            "raw_message": cleaned_message,
            "session_id": session_id,
            "new_session": False,
            "source": "discord_commitment_followup",
            "due_at": due_at.isoformat() if due_at else None,
            "timezone": timezone_name,
            **self._current_channel_payload(ctx),
        }
        async with ctx.typing():
            try:
                result = await api_post("/life/commitments/capture", payload)
                if result.get("session_id") and result.get("needs_follow_up"):
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, int(result["session_id"]))
                elif self._get_active_session_id(ctx, COMMITMENT_SESSION_NAME) == session_id:
                    self._set_active_session_id(ctx, COMMITMENT_SESSION_NAME, None)
                await self._send_commitment_embed(ctx, result, heading="Commitment Follow-up")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    await ctx.send(
                        f"No commitment session found for #{explicit_target_id or session_id}. "
                        "Use the Inbox id from the `Inbox` field, or `!commitfollow session #<session_id> <answer>`."
                    )
                    return
                await ctx.send(f"Failed to continue commitment capture: {self._trim_error(exc)}")
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
                    f"{item.get('focus_reason') or item.get('priority_reason') or 'focus now'}"
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
