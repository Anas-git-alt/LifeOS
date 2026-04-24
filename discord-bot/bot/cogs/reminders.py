"""Reminders cog — prayer times, check-ins, and scheduled nudges."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from bot.utils import api_get, api_post

PRAYER_EMOJI_TO_STATUS = {"✅": "on_time", "🕒": "late", "❌": "missed"}
VALID_PRAYER_STATUSES = {"on_time", "late", "missed"}
VALID_PRAYERS = {"fajr": "Fajr", "dhuhr": "Dhuhr", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}
_SLEEP_TIME_PATTERN = re.compile(
    r"\b(bed(?:time)?|sleep|wake|woke|wakeup|wake-up|up)\s*(?:at)?\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)


def _owner_ids() -> set[int]:
    owners: set[int] = set()
    for raw in os.getenv("DISCORD_OWNER_IDS", "").split(","):
        raw = raw.strip()
        if raw.isdigit():
            owners.add(int(raw))
    return owners


class RemindersCog(commands.Cog, name="Reminders"):
    def __init__(self, bot):
        self.bot = bot
        self.owner_ids = _owner_ids()
        self.daily_checkin.start()
        self.prayer_dispatch.start()

    def cog_unload(self):
        self.daily_checkin.cancel()
        self.prayer_dispatch.cancel()

    def _is_owner(self, user_id: int) -> bool:
        return user_id in self.owner_ids

    def _find_channel(self, channel_name: str) -> discord.TextChannel | None:
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if channel.name == channel_name and channel.permissions_for(guild.me).send_messages:
                    return channel
        return None

    @staticmethod
    def _split_number_prefix(raw: str, caster):
        text = (raw or "").strip()
        if not text:
            return None, ""
        first, *rest = text.split(maxsplit=1)
        try:
            value = caster(first)
        except ValueError:
            return None, text
        return value, (rest[0] if rest else "").strip()

    @staticmethod
    def _clock_value(hour_text: str, minute_text: str | None, meridian_text: str | None) -> str | None:
        hour = int(hour_text)
        minute = int(minute_text or 0)
        meridian = (meridian_text or "").lower()
        if meridian == "pm" and hour < 12:
            hour += 12
        if meridian == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    def _parse_sleep_details(self, details: str) -> dict:
        hours, parsed_note = self._split_number_prefix(details, float)
        note = parsed_note if hours is not None else (details or "").strip()
        bedtime = None
        wake_time = None
        spans = []
        for match in _SLEEP_TIME_PATTERN.finditer(note):
            value = self._clock_value(match.group(2), match.group(3), match.group(4))
            if not value:
                continue
            label = match.group(1).lower()
            if label.startswith(("bed", "sleep")):
                bedtime = value
            else:
                wake_time = value
            spans.append(match.span())
        cleaned = note
        for start, end in sorted(spans, reverse=True):
            cleaned = f"{cleaned[:start]} {cleaned[end:]}"
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
        return {
            "kind": "sleep",
            "hours": hours,
            "bedtime": bedtime,
            "wake_time": wake_time,
            "note": cleaned or None,
        }

    @commands.command(name="prayer")
    async def prayer_check(self, ctx):
        """Log a prayer and get the next prayer time."""
        async with ctx.typing():
            try:
                result = await api_post("/agents/chat", {"agent_name": "prayer-deen", "message": "I just prayed. Coach me briefly."})
                embed = discord.Embed(
                    title="🕌 Prayer Check-in",
                    description=result.get("response", "MashaAllah, keep it up!"),
                    color=0x16A34A,
                )
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"🤲 Alhamdulillah for praying! (Agent offline: {str(e)[:100]})")

    @commands.command(name="prayertoday")
    async def prayer_today(self, ctx):
        """Show today's prayer schedule."""
        try:
            data = await api_get("/prayer/schedule/today")
            lines = []
            for row in data.get("windows", []):
                starts = str(row["starts_at"]).replace("T", " ")[:16]
                ends = str(row["ends_at"]).replace("T", " ")[:16]
                lines.append(f"• **{row['prayer_name']}**: {starts} → {ends} UTC")
            header = f"🕌 Prayer Schedule ({data.get('city')}, {data.get('country')})"
            if data.get("is_ramadan"):
                header += " | Ramadan"
            next_prayer = data.get("next_prayer") or "none"
            embed = discord.Embed(title=header, description="\n".join(lines) or "No windows found.", color=0x16A34A)
            embed.set_footer(text=f"Date {data.get('date')} | Next: {next_prayer}")
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Failed to load prayer schedule: {str(exc)[:180]}")

    @commands.command(name="prayerlog")
    async def prayer_log(self, ctx, prayer_date: str, prayer_name: str, status: str, *, note: str = ""):
        """Retroactive prayer log: !prayerlog 2026-03-01 Fajr late [note]."""
        normalized_prayer = VALID_PRAYERS.get(prayer_name.strip().lower())
        normalized_status = status.strip().lower()
        if not normalized_prayer:
            await ctx.send("Invalid prayer name. Use: Fajr, Dhuhr, Asr, Maghrib, Isha.")
            return
        if normalized_status not in VALID_PRAYER_STATUSES:
            await ctx.send("Invalid status. Use: on_time, late, missed.")
            return
        payload = {
            "prayer_date": prayer_date,
            "prayer_name": normalized_prayer,
            "status": normalized_status,
            "note": note or None,
            "source": "command_retroactive",
            "discord_user_id": str(ctx.author.id),
        }
        try:
            result = await api_post("/prayer/checkin/retroactive", payload)
            await ctx.send(
                f"Logged retroactive {result['prayer_name']} on {result['prayer_date']}: "
                f"raw={result['status_raw']} scored={result['status_scored']}"
            )
        except Exception as exc:
            await ctx.send(f"Failed to log retroactive prayer: {str(exc)[:200]}")

    @commands.command(name="quran")
    async def quran(self, ctx, end_page: int, start_page: int = 0, *, note: str = ""):
        """Log Quran reading: !quran 25 (auto-start from bookmark) or !quran 25 10 (pages 10-25)."""
        try:
            result = await api_post(
                "/prayer/habits/quran/log",
                {
                    "end_page": end_page,
                    "start_page": start_page if start_page > 0 else None,
                    "note": note or None,
                    "source": "discord",
                },
            )
            await ctx.send(
                f"📖 Quran logged ({result['local_date']}): pages {result['start_page']}–{result['end_page']} "
                f"({result['pages_read']} pages read)."
            )
        except Exception as exc:
            await ctx.send(f"Failed to log Quran progress: {str(exc)[:180]}")

    @commands.command(name="quranprogress")
    async def quranprogress(self, ctx):
        """Show Quran reading progress and current bookmark."""
        try:
            data = await api_get("/prayer/habits/quran/progress")
            embed = discord.Embed(
                title="📖 Quran Progress",
                description=(
                    f"**Current Bookmark:** Page {data['current_page']} of {data['total_pages']}\n"
                    f"**Total Pages Read:** {data['pages_read_total']}\n"
                    f"**Khatma Progress:** {data['completion_pct']}%"
                ),
                color=0x16A34A,
            )
            if data.get("recent_readings"):
                recent = data["recent_readings"][:5]
                lines = [f"• p.{r['start_page']}–{r['end_page']} ({r['pages_read']}p) — {r['local_date']}" for r in recent]
                embed.add_field(name="Recent", value="\n".join(lines), inline=False)
            await ctx.send(embed=embed)
        except Exception as exc:
            await ctx.send(f"Failed to get Quran progress: {str(exc)[:180]}")

    @commands.command(name="sleep")
    async def log_sleep_quick(self, ctx, *, details: str = ""):
        """Quick sleep log. Usage: !sleep 7.5 bed 23:30 wake 07:10 solid"""
        payload = self._parse_sleep_details(details)
        try:
            result = await api_post("/life/daily-log", payload)
            await ctx.send(f"😴 {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log sleep: {str(exc)[:180]}")

    @commands.command(name="meal")
    async def log_meal_quick(self, ctx, *, details: str = ""):
        """Quick meal log. Usage: !meal 2 chicken rice / !meal protein shake"""
        count, parsed_note = self._split_number_prefix(details, int)
        note = parsed_note if count is not None else details.strip()
        try:
            result = await api_post(
                "/life/daily-log",
                {
                    "kind": "meal",
                    "count": count or 1,
                    "note": note or None,
                    "protein_hit": "protein" in note.lower() if note else None,
                },
            )
            await ctx.send(f"🍽️ {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log meal: {str(exc)[:180]}")

    @commands.command(name="train")
    async def log_training_quick(self, ctx, *, details: str = ""):
        """Quick training log. Usage: !train done push day / !train rest sore today"""
        status = "done"
        note = details.strip()
        if note:
            first, *rest = note.split(maxsplit=1)
            if first.lower() in {"done", "rest", "missed"}:
                status = first.lower()
                note = (rest[0] if rest else "").strip()
        try:
            result = await api_post(
                "/life/daily-log",
                {"kind": "training", "status": status, "note": note or None},
            )
            await ctx.send(f"💪 {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log training: {str(exc)[:180]}")

    @commands.command(name="water")
    async def log_water_quick(self, ctx, *, details: str = ""):
        """Quick hydration log. Usage: !water 2 after walk"""
        count, parsed_note = self._split_number_prefix(details, int)
        note = parsed_note if count is not None else details.strip()
        try:
            result = await api_post(
                "/life/daily-log",
                {"kind": "hydration", "count": count or 1, "note": note or None},
            )
            await ctx.send(f"💧 {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log water: {str(exc)[:180]}")

    @commands.command(name="shutdown")
    async def log_shutdown_quick(self, ctx, *, note: str = ""):
        """Quick shutdown log. Usage: !shutdown inbox zero and tomorrow ready"""
        try:
            result = await api_post(
                "/life/daily-log",
                {"kind": "shutdown", "done": True, "note": note.strip() or None},
            )
            await ctx.send(f"🌙 {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log shutdown: {str(exc)[:180]}")

    @commands.command(name="family")
    async def log_family_quick(self, ctx, *, note: str = ""):
        """Quick family anchor log. Usage: !family called parents"""
        try:
            result = await api_post(
                "/life/daily-log",
                {"kind": "family", "done": True, "note": note.strip() or None},
            )
            await ctx.send(f"💕 {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log family action: {str(exc)[:180]}")

    @commands.command(name="priority")
    async def log_priority_quick(self, ctx, *, note: str = ""):
        """Quick priority anchor log. Usage: !priority shipped invoice"""
        try:
            result = await api_post(
                "/life/daily-log",
                {"kind": "priority", "count": 1, "note": note.strip() or None},
            )
            await ctx.send(f"🎯 {result['message']}")
        except Exception as exc:
            await ctx.send(f"Failed to log priority: {str(exc)[:180]}")

    @commands.command(name="tahajjud")
    async def tahajjud(self, ctx, state: str, prayer_date: str | None = None):
        """Log tahajjud: !tahajjud done [YYYY-MM-DD]."""
        state_norm = state.strip().lower()
        if state_norm not in {"done", "missed"}:
            await ctx.send("State must be `done` or `missed`.")
            return
        try:
            result = await api_post(
                "/prayer/habits/tahajjud",
                {"date": prayer_date, "done": state_norm == "done"},
            )
            await ctx.send(f"🌙 Tahajjud logged for {result['local_date']}: {state_norm}.")
        except Exception as exc:
            await ctx.send(f"Failed to log tahajjud: {str(exc)[:180]}")

    @commands.command(name="adhkar")
    async def adhkar(self, ctx, period: str, state: str, prayer_date: str | None = None):
        """Log adhkar: !adhkar morning done [YYYY-MM-DD]."""
        period_norm = period.strip().lower()
        state_norm = state.strip().lower()
        if period_norm not in {"morning", "evening"}:
            await ctx.send("Period must be `morning` or `evening`.")
            return
        if state_norm not in {"done", "missed"}:
            await ctx.send("State must be `done` or `missed`.")
            return
        try:
            result = await api_post(
                "/prayer/habits/adhkar",
                {"date": prayer_date, "period": period_norm, "done": state_norm == "done"},
            )
            await ctx.send(f"🤲 Adhkar ({period_norm}) logged for {result['local_date']}: {state_norm}.")
        except Exception as exc:
            await ctx.send(f"Failed to log adhkar: {str(exc)[:180]}")

    @commands.command(name="workout")
    async def log_workout(self, ctx, *, details: str = "completed a workout"):
        """Log a workout. Usage: !workout pushed legs today, 45 min"""
        async with ctx.typing():
            try:
                result = await api_post(
                    "/agents/chat",
                    {"agent_name": "health-fitness", "message": f"I just {details}. Give me brief feedback and what to do next time."},
                )
                embed = discord.Embed(
                    title="💪 Workout Logged",
                    description=result.get("response", "Great job staying consistent!"),
                    color=0xF59E0B,
                )
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"💪 Workout logged! (Agent offline: {str(e)[:100]})")

    @commands.command(name="wife")
    async def wife_note(self, ctx, *, note: str):
        """Log something for the marriage agent. Usage: !wife promised to take her out Friday"""
        async with ctx.typing():
            try:
                result = await api_post(
                    "/agents/chat",
                    {"agent_name": "marriage-family", "message": f"Record this and remind me later: {note}"},
                )
                embed = discord.Embed(
                    title="💕 Commitment Recorded",
                    description=result.get("response", "Got it! I'll remind you."),
                    color=0xEC4899,
                )
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"💕 Noted! (Agent offline: {str(e)[:100]})")

    @tasks.loop(minutes=1)
    async def prayer_dispatch(self):
        await self.bot.wait_until_ready()
        try:
            due = await api_get("/prayer/due-reminders")
            for item in due.get("items", []):
                channel = self._find_channel(item.get("channel_name", "prayer-tracker"))
                if not channel:
                    continue
                title = f"🕌 {item['prayer_name']} Reminder"
                if item.get("is_ramadan"):
                    title += " | Ramadan"
                desc = (
                    f"Prayer window: until `{item['ends_at'][:16].replace('T', ' ')}` UTC\n"
                    "React now:\n"
                    "✅ on-time | 🕒 late | ❌ missed"
                )
                embed = discord.Embed(title=title, description=desc, color=0x16A34A)
                embed.set_footer(text=f"prayer:{item['prayer_date']}:{item['prayer_name']}:{item['window_id']}")
                msg = await channel.send(embed=embed)
                for emoji in PRAYER_EMOJI_TO_STATUS:
                    await msg.add_reaction(emoji)
                await api_post("/prayer/reminder-sent", {"window_id": item["window_id"], "discord_message_id": str(msg.id)})

            nudges = await api_get("/prayer/due-nudges")
            for item in nudges.get("items", []):
                channel = self._find_channel(item.get("channel_name", "prayer-tracker"))
                if not channel:
                    continue
                await channel.send(
                    f"⏳ Reminder: `{item['prayer_name']}` window closes soon (`{item['ends_at'][:16].replace('T', ' ')}` UTC). "
                    "Please react before deadline."
                )
                await api_post("/prayer/nudge-sent", {"window_id": item["window_id"]})
        except Exception:
            return

    @tasks.loop(hours=6)
    async def daily_checkin(self):
        """Periodic health check — sends alert to first text channel if backend is down."""
        await self.bot.wait_until_ready()
        try:
            await api_get("/health")
        except Exception:
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        await channel.send(
                            "🚨 **LifeOS Alert**: Backend is unreachable! "
                            "Check `docker compose logs backend` for errors."
                        )
                        return

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        emoji = str(payload.emoji)
        if emoji not in PRAYER_EMOJI_TO_STATUS:
            return
        if not self._is_owner(payload.user_id):
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
        footer = (embed.footer.text or "").strip() if embed.footer else ""
        if not footer.startswith("prayer:"):
            return
        parts = footer.split(":")
        if len(parts) == 4:
            _, prayer_date, prayer_name, raw_window_id = parts
        elif len(parts) == 3:
            _, prayer_date, prayer_name = parts
            raw_window_id = ""
        else:
            return

        status = PRAYER_EMOJI_TO_STATUS[emoji]
        payload_data = {
            "prayer_date": prayer_date,
            "prayer_name": prayer_name,
            "status": status,
            "source": "discord_reaction",
            "discord_user_id": str(payload.user_id),
        }
        if raw_window_id.isdigit():
            payload_data["prayer_window_id"] = int(raw_window_id)
        try:
            await api_post("/prayer/checkin", payload_data)
            await channel.send(f"Logged `{prayer_name}` for {prayer_date}: {status}.")
        except Exception as exc:
            await channel.send(f"Failed to log prayer check-in: {str(exc)[:200]}")

    @commands.command(name="goal")
    async def create_goal(self, ctx, domain: str, *, title: str):
        """Create a goal: !goal deen Memorize Surat Al-Baqara."""
        valid_domains = {"deen", "family", "work", "health", "planning"}
        if domain.lower() not in valid_domains:
            await ctx.send(f"Invalid domain. Use: {', '.join(sorted(valid_domains))}")
            return
        try:
            result = await api_post(
                "/life/items",
                {
                    "domain": domain.lower(),
                    "title": title.strip(),
                    "kind": "goal",
                    "priority": "medium",
                    "source_agent": "discord",
                },
            )
            await ctx.send(f"🎯 Goal created (#{result['id']}): **{result['title']}** [{result['domain']}]")
        except Exception as exc:
            await ctx.send(f"Failed to create goal: {str(exc)[:180]}")

async def setup(bot):
    await bot.add_cog(RemindersCog(bot))
