"""Natural-language automation flows for jobs and agent creation."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from bot.nl import DEFAULT_TIMEZONE, parse_agent_prompt, parse_schedule_prompt, parse_schedule_value
from bot.utils import api_get, api_post


class AutomationCog(commands.Cog, name="Automation"):
    def __init__(self, bot):
        self.bot = bot
        self.pending: dict[tuple[int, int, int], dict] = {}
        self._zero_width_pattern = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")

    def _state_key(self, ctx) -> tuple[int, int, int]:
        guild_id = ctx.guild.id if ctx.guild else 0
        return (guild_id, ctx.channel.id, ctx.author.id)

    @staticmethod
    def _question_for(field: str) -> str:
        questions = {
            "agent_name": "Which agent should run this job? (example: `daily-planner`)",
            "target_channel": "Which target channel? (example: `#fitness-log` or `<#123456789012345678>`) ",
            "schedule": (
                "What schedule should this use? Try `every weekday at 7:30`, "
                "`tomorrow at 9am`, or `in 10 min`."
            ),
            "timezone": "Which timezone should this job use? (example: `Africa/Casablanca`)",
            "name": "What should the agent name be? (example: `focus-coach`)",
            "purpose": "What is this agent's purpose in one sentence?",
            "discord_channel": "Which channel should this agent map to? (example: `#planning`)",
            "cadence": "What cadence should this agent run on? (example: `every day at 8:00`)",
            "approval_policy": "What approval policy? (`approval auto`, `approval always`, or `approval never`)",
        }
        return questions.get(field, f"Please provide `{field}`.")

    @staticmethod
    def _silent_answer(value: str) -> bool:
        lowered = value.lower().strip()
        return lowered in {"silent", "silently", "background", "no discord post", "no notification"}

    def _normalize_channel_reference(self, value: str) -> str:
        cleaned = self._zero_width_pattern.sub("", str(value or ""))
        cleaned = re.sub(r"#\s+", "#", cleaned)
        return cleaned.strip()

    def _resolve_target_channel(self, ctx, raw_value: str) -> tuple[dict | None, str | None]:
        value = self._normalize_channel_reference(raw_value)
        if not value:
            return None, "Which target channel should I use? Try `#fitness-log` or `<#123456789012345678>`."

        if self._silent_answer(value):
            return {"notification_mode": "silent", "target_channel": None, "target_channel_id": None}, None

        if value.startswith("<#") and value.endswith(">"):
            channel_id = value[2:-1].strip()
            if not channel_id.isdigit():
                return None, "That channel mention looks invalid. Try something like `<#123456789012345678>`."
            if not ctx.guild:
                return None, "I can only validate a channel mention inside a Discord server."
            channel = ctx.guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                return None, "I couldn't resolve that to a text channel in this server."
            return {
                "notification_mode": "channel",
                "target_channel": channel.name,
                "target_channel_id": str(channel.id),
            }, None

        channel_name = value.lstrip("#").strip()
        if not channel_name:
            return None, "Which target channel should I use? Try `#fitness-log`."

        if ctx.guild:
            channel = next((item for item in ctx.guild.text_channels if item.name == channel_name), None)
            if channel:
                return {
                    "notification_mode": "channel",
                    "target_channel": channel.name,
                    "target_channel_id": str(channel.id),
                }, None

        return {
            "notification_mode": "channel",
            "target_channel": channel_name,
            "target_channel_id": None,
        }, None

    def _enrich_schedule_data(self, ctx, data: dict) -> str | None:
        if data.get("notification_mode") != "channel":
            data["target_channel"] = None
            data["target_channel_id"] = None
            return None
        if data.get("target_channel_id"):
            resolved, error = self._resolve_target_channel(ctx, f"<#{data['target_channel_id']}>")
            if error:
                return error
            data.update(resolved or {})
            return None
        if data.get("target_channel"):
            resolved, error = self._resolve_target_channel(ctx, f"#{data['target_channel']}")
            if error and str(data.get("target_channel")).startswith("<#"):
                return error
            if resolved:
                data.update(resolved)
        return None

    @staticmethod
    def _format_local_run(run_at_value: datetime | str | None, timezone_name: str) -> str:
        if not run_at_value:
            return "n/a"
        if isinstance(run_at_value, str):
            try:
                run_at = datetime.fromisoformat(run_at_value.replace("Z", "+00:00"))
            except ValueError:
                return run_at_value
        else:
            run_at = run_at_value
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        return run_at.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M")

    def _schedule_summary(self, data: dict) -> str:
        if data.get("schedule_type") == "once":
            return f"Once at {self._format_local_run(data.get('run_at'), data.get('timezone', DEFAULT_TIMEZONE))}"
        return f"Cron {data.get('cron_expression')} ({data.get('timezone', DEFAULT_TIMEZONE)})"

    @staticmethod
    def _notification_summary(data: dict) -> str:
        if data.get("notification_mode") == "silent":
            return "silent/background"
        if data.get("target_channel_id"):
            return f"post in <#{data['target_channel_id']}>"
        if data.get("target_channel"):
            return f"post in #{data['target_channel']}"
        return "post in mapped agent channel"

    @staticmethod
    def _job_status_label(row: dict) -> str:
        if row.get("schedule_type") == "once" and row.get("completed_at"):
            return "missed" if row.get("last_status") == "missed" else "completed"
        if row.get("paused"):
            return "paused"
        return "on" if row.get("enabled") else "off"

    def _job_schedule_label(self, row: dict) -> str:
        if row.get("schedule_type") == "once":
            when = self._format_local_run(row.get("run_at"), row.get("timezone", DEFAULT_TIMEZONE))
            return f"Once at {when}"
        return f"Cron {row.get('cron_expression')}"

    @staticmethod
    def _job_target_label(row: dict) -> str:
        if row.get("notification_mode") == "silent":
            return "silent"
        if row.get("target_channel_id"):
            return f"<#{row['target_channel_id']}>"
        if row.get("target_channel"):
            return f"#{row['target_channel']}"
        return "mapped channel"

    async def _submit_schedule_state(self, ctx, state: dict) -> None:
        if state["type"] == "job":
            await self._submit_job_proposal(ctx, state["data"])
        else:
            await self._submit_agent_proposal(ctx, state["data"])

    @commands.command(name="schedule")
    async def create_job_from_nl(self, ctx, *, prompt: str):
        parsed = parse_schedule_prompt(prompt)
        state = {"type": "job", "data": parsed["data"], "missing": parsed["missing"]}
        channel_error = self._enrich_schedule_data(ctx, state["data"])
        if channel_error:
            await ctx.send(channel_error)
            return
        if state["missing"]:
            self.pending[self._state_key(ctx)] = state
            extra = f" {parsed['errors'][0]}" if parsed["errors"] else ""
            await ctx.send(
                f"Need more info before creating the job.{extra} {self._question_for(state['missing'][0])}"
            )
            return
        if parsed["errors"]:
            await ctx.send(parsed["errors"][0])
            return
        await self._submit_job_proposal(ctx, state["data"])

    @commands.command(name="spawnagent")
    async def create_agent_from_nl(self, ctx, *, prompt: str):
        parsed = parse_agent_prompt(prompt)
        state = {"type": "agent", "data": parsed["data"], "missing": parsed["missing"]}
        if state["missing"]:
            self.pending[self._state_key(ctx)] = state
            await ctx.send(f"Need more info before creating the agent. {self._question_for(state['missing'][0])}")
            return
        await self._submit_agent_proposal(ctx, state["data"])

    @commands.command(name="cancel")
    async def cancel_followup(self, ctx):
        removed = self.pending.pop(self._state_key(ctx), None)
        if removed:
            await ctx.send("Cleared the pending automation flow.")
            return
        await ctx.send("No pending automation flow to cancel.")

    @commands.command(name="reply")
    async def continue_followup(self, ctx, *, answer: str):
        key = self._state_key(ctx)
        state = self.pending.get(key)
        if not state:
            await ctx.send("No pending creation flow. Start with `!schedule ...` or `!spawnagent ...`.")
            return

        field = state["missing"][0]
        value = answer.strip()
        if field == "target_channel":
            resolved, error = self._resolve_target_channel(ctx, value)
            if error:
                await ctx.send(error)
                return
            state["data"].update(resolved or {})
        elif field == "schedule":
            parsed = parse_schedule_value(value, default_timezone=state["data"].get("timezone", DEFAULT_TIMEZONE))
            if not parsed["data"]:
                await ctx.send(parsed["errors"][0] if parsed["errors"] else "I still couldn't parse that schedule.")
                return
            state["data"].update(parsed["data"])
        elif field == "cron_expression":
            parsed = parse_schedule_value(value, default_timezone=state["data"].get("timezone", DEFAULT_TIMEZONE))
            if parsed["data"].get("schedule_type") != "cron":
                await ctx.send("I couldn't parse that cadence. Try: `every day at 8:00`.")
                return
            state["data"]["cron_expression"] = parsed["data"]["cron_expression"]
        elif field == "cadence":
            parsed = parse_schedule_value(value, default_timezone=state["data"].get("timezone", DEFAULT_TIMEZONE))
            if parsed["data"].get("schedule_type") != "cron":
                await ctx.send("I couldn't parse that cadence. Try: `every day at 8:00`.")
                return
            state["data"]["cadence"] = parsed["data"]["cron_expression"]
        elif field == "approval_policy":
            parsed = parse_agent_prompt(value)
            if "approval_policy" in parsed["missing"]:
                await ctx.send("Provide approval policy as `approval auto`, `approval always`, or `approval never`.")
                return
            state["data"]["config_json"] = parsed["data"]["config_json"]
        elif field == "purpose":
            state["data"]["description"] = value
            agent_name = state["data"].get("name", "LifeOS agent")
            state["data"]["system_prompt"] = f"You are {agent_name}. Purpose: {value}"
        elif field == "discord_channel":
            state["data"][field] = value.lstrip("#")
        else:
            state["data"][field] = value

        state["missing"] = state["missing"][1:]
        if state["type"] == "job":
            channel_error = self._enrich_schedule_data(ctx, state["data"])
            if channel_error:
                await ctx.send(channel_error)
                return
        if state["missing"]:
            self.pending[key] = state
            await ctx.send(self._question_for(state["missing"][0]))
            return

        self.pending.pop(key, None)
        await self._submit_schedule_state(ctx, state)

    @commands.command(name="jobs")
    async def list_jobs(self, ctx, agent_name: str = ""):
        try:
            path = "/jobs/"
            if agent_name:
                path += f"?agent_name={agent_name}"
            rows = await api_get(path)
            if not rows:
                await ctx.send("No jobs found.")
                return
            lines = []
            for row in rows[:15]:
                lines.append(
                    f"#{row['id']} {row['name']} · {self._job_schedule_label(row)} · "
                    f"{self._job_target_label(row)} · {self._job_status_label(row)}"
                )
            await ctx.send("Jobs:\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to list jobs: {str(exc)[:200]}")

    @commands.command(name="job")
    async def get_job(self, ctx, job_id: int):
        try:
            row = await api_get(f"/jobs/{job_id}")
            schedule_line = (
                f"**Schedule:** Once at {self._format_local_run(row.get('run_at'), row.get('timezone', DEFAULT_TIMEZONE))}"
                if row.get("schedule_type") == "once"
                else f"**Schedule:** {row.get('cron_expression')} ({row.get('timezone')})"
            )
            lines = [
                f"**Name:** {row.get('name')}",
                f"**Agent:** {row.get('agent_name') or 'system'}",
                schedule_line,
                f"**Notify:** {self._job_target_label(row)}",
                f"**Status:** {self._job_status_label(row)}",
                f"**Last:** {row.get('last_status') or 'n/a'}",
                f"**Next Run:** {str(row.get('next_run_at') or 'n/a')[:19].replace('T', ' ')}",
            ]
            if row.get("completed_at"):
                lines.append(f"**Completed:** {str(row.get('completed_at'))[:19].replace('T', ' ')}")
            await ctx.send(f"Job #{job_id}\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to load job: {str(exc)[:200]}")

    @commands.command(name="pausejob")
    async def pause_job(self, ctx, job_id: int):
        try:
            row = await api_post(f"/jobs/{job_id}/pause", {})
            await ctx.send(f"Paused job #{row['id']}: {row['name']}")
        except Exception as exc:
            await ctx.send(f"Failed to pause job: {str(exc)[:200]}")

    @commands.command(name="resumejob")
    async def resume_job(self, ctx, job_id: int):
        try:
            row = await api_post(f"/jobs/{job_id}/resume", {})
            await ctx.send(f"Resumed job #{row['id']}: {row['name']}")
        except Exception as exc:
            await ctx.send(f"Failed to resume job: {str(exc)[:200]}")

    @commands.command(name="jobruns")
    async def list_job_runs(self, ctx, job_id: int, limit: int = 5):
        safe_limit = max(1, min(limit, 20))
        try:
            rows = await api_get(f"/jobs/{job_id}/runs?limit={safe_limit}")
            if not rows:
                await ctx.send(f"No run logs found for job #{job_id}.")
                return
            lines = []
            for row in rows:
                finished = str(row.get("finished_at", ""))[:16].replace("T", " ")
                err = f" | err={str(row.get('error'))[:60]}" if row.get("error") else ""
                lines.append(f"#{row['id']} {row.get('status')} at {finished}{err}")
            await ctx.send(f"Recent runs for job #{job_id}:\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to list job runs: {str(exc)[:200]}")

    async def _submit_job_proposal(self, ctx, data: dict):
        run_at_value = data.get("run_at")
        if isinstance(run_at_value, datetime) and run_at_value.tzinfo is None:
            run_at_value = run_at_value.replace(tzinfo=timezone.utc)
        details = {
            "name": data["name"],
            "description": data.get("description"),
            "agent_name": data["agent_name"],
            "job_type": data.get("job_type", "agent_nudge"),
            "schedule_type": data.get("schedule_type", "cron"),
            "cron_expression": data.get("cron_expression"),
            "run_at": run_at_value.isoformat() if isinstance(run_at_value, datetime) else run_at_value,
            "timezone": data.get("timezone", DEFAULT_TIMEZONE),
            "notification_mode": data.get("notification_mode", "silent"),
            "target_channel": data.get("target_channel"),
            "target_channel_id": data.get("target_channel_id"),
            "prompt_template": data.get("prompt_template"),
            "enabled": True,
            "paused": False,
            "approval_required": True,
            "source": "discord_nl",
            "created_by": str(ctx.author),
            "config_json": data.get("config_json"),
        }
        response = await api_post(
            "/jobs/propose",
            {
                "summary": f"Create job '{details['name']}' for agent '{details['agent_name']}'",
                "details": details,
                "requested_by": str(ctx.author),
                "source": "discord_nl",
            },
        )
        await ctx.send(
            "\n".join(
                [
                    f"Job proposal queued as PendingAction #{response['pending_action_id']}.",
                    f"Agent: `{details['agent_name']}`",
                    f"Schedule: {self._schedule_summary(details)}",
                    f"Notify: {self._notification_summary(details)}",
                    f"Approve it with `!approve {response['pending_action_id']}`.",
                ]
            )
        )

    async def _submit_agent_proposal(self, ctx, data: dict):
        details = {
            "name": data["name"],
            "description": data["description"],
            "system_prompt": data["system_prompt"],
            "provider": data.get("provider", "openrouter"),
                    "model": data.get("model", "openrouter/free"),
            "fallback_provider": data.get("fallback_provider"),
            "fallback_model": data.get("fallback_model"),
            "discord_channel": data["discord_channel"],
            "cadence": data["cadence"],
            "enabled": True,
            "config_json": data.get("config_json", {"approval_policy": "auto"}),
        }
        response = await api_post(
            "/agents/propose",
            {
                "summary": f"Create agent '{details['name']}' mapped to #{details['discord_channel']}",
                "details": details,
                "requested_by": str(ctx.author),
                "source": "discord_nl",
            },
        )
        await ctx.send(
            f"Agent proposal queued as PendingAction #{response['pending_action_id']}. Approve it with `!approve {response['pending_action_id']}`."
        )


async def setup(bot):
    await bot.add_cog(AutomationCog(bot))
