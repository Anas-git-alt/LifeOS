"""Natural-language automation flows for jobs and agent creation."""

from __future__ import annotations

from discord.ext import commands

from bot.nl import parse_agent_prompt, parse_schedule_prompt
from bot.utils import api_get, api_post


class AutomationCog(commands.Cog, name="Automation"):
    def __init__(self, bot):
        self.bot = bot
        self.pending: dict[tuple[int, int, int], dict] = {}

    def _state_key(self, ctx) -> tuple[int, int, int]:
        guild_id = ctx.guild.id if ctx.guild else 0
        return (guild_id, ctx.channel.id, ctx.author.id)

    @staticmethod
    def _question_for(field: str) -> str:
        questions = {
            "agent_name": "Which agent should run this job? (example: `daily-planner`)",
            "target_channel": "Which target channel? (example: `#fitness-log`)",
            "cron_expression": "What schedule should this use? (example: `every weekday at 7:30`)",
            "timezone": "Which timezone should this job use? (example: `Africa/Casablanca`)",
            "name": "What should the agent name be? (example: `focus-coach`)",
            "purpose": "What is this agent's purpose in one sentence?",
            "discord_channel": "Which channel should this agent map to? (example: `#planning`)",
            "cadence": "What cadence should this agent run on? (example: `every day at 8:00`)",
            "approval_policy": "What approval policy? (`approval auto`, `approval always`, or `approval never`)",
        }
        return questions.get(field, f"Please provide `{field}`.")

    @commands.command(name="schedule")
    async def create_job_from_nl(self, ctx, *, prompt: str):
        parsed = parse_schedule_prompt(prompt)
        state = {"type": "job", "data": parsed["data"], "missing": parsed["missing"]}
        if state["missing"]:
            self.pending[self._state_key(ctx)] = state
            await ctx.send(f"Need more info before creating the job. {self._question_for(state['missing'][0])}")
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
            value = value.lstrip("#")
        elif field == "discord_channel":
            value = value.lstrip("#")
        elif field == "cron_expression":
            parsed = parse_schedule_prompt(value)
            if "cron_expression" in parsed["missing"]:
                await ctx.send("I couldn't parse that schedule. Try: `every weekday at 7:30`.")
                return
            value = parsed["data"]["cron_expression"]
        elif field == "cadence":
            parsed = parse_schedule_prompt(value)
            if "cron_expression" in parsed["missing"]:
                await ctx.send("I couldn't parse that cadence. Try: `every day at 8:00`.")
                return
            value = parsed["data"]["cron_expression"]
        elif field == "approval_policy":
            parsed = parse_agent_prompt(value)
            if "approval_policy" in parsed["missing"]:
                await ctx.send("Provide approval policy as `approval auto`, `approval always`, or `approval never`.")
                return
            state["data"]["config_json"] = parsed["data"]["config_json"]
            state["missing"] = state["missing"][1:]
            if state["missing"]:
                self.pending[key] = state
                await ctx.send(self._question_for(state["missing"][0]))
                return
            self.pending.pop(key, None)
            if state["type"] == "job":
                await self._submit_job_proposal(ctx, state["data"])
            else:
                await self._submit_agent_proposal(ctx, state["data"])
            return

        if field == "purpose":
            state["data"]["description"] = value
            agent_name = state["data"].get("name", "LifeOS agent")
            state["data"]["system_prompt"] = f"You are {agent_name}. Purpose: {value}"
        else:
            state["data"][field] = value

        state["missing"] = state["missing"][1:]
        if state["missing"]:
            self.pending[key] = state
            await ctx.send(self._question_for(state["missing"][0]))
            return

        self.pending.pop(key, None)
        if state["type"] == "job":
            await self._submit_job_proposal(ctx, state["data"])
        else:
            await self._submit_agent_proposal(ctx, state["data"])

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
                status = "paused" if row.get("paused") else ("on" if row.get("enabled") else "off")
                lines.append(
                    f"#{row['id']} {row['name']} · {row.get('cron_expression')} · {row.get('timezone')} · {status}"
                )
            await ctx.send("Jobs:\n" + "\n".join(lines))
        except Exception as exc:
            await ctx.send(f"Failed to list jobs: {str(exc)[:200]}")

    async def _submit_job_proposal(self, ctx, data: dict):
        details = {
            "name": data["name"],
            "description": data.get("description"),
            "agent_name": data["agent_name"],
            "job_type": data.get("job_type", "agent_nudge"),
            "cron_expression": data["cron_expression"],
            "timezone": data.get("timezone", "Africa/Casablanca"),
            "target_channel": data.get("target_channel"),
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
            f"Job proposal queued as PendingAction #{response['pending_action_id']}. Approve it with `!approve {response['pending_action_id']}`."
        )

    async def _submit_agent_proposal(self, ctx, data: dict):
        details = {
            "name": data["name"],
            "description": data["description"],
            "system_prompt": data["system_prompt"],
            "provider": data.get("provider", "openrouter"),
            "model": data.get("model", "openrouter/auto"),
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
