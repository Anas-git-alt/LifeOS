"""Reminders cog — prayer times, check-ins, and scheduled nudges."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from bot.utils import api_get, api_post

PRAYER_EMOJI_TO_STATUS = {"✅": "on_time", "🕒": "late", "❌": "missed"}
VALID_PRAYER_STATUSES = {"on_time", "late", "missed"}
VALID_PRAYERS = {"fajr": "Fajr", "dhuhr": "Dhuhr", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}


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
    async def quran(self, ctx, juz: int, pages: int = 0, *, note: str = ""):
        """Log Quran reading: !quran 2 4 [note]."""
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        try:
            result = await api_post(
                "/prayer/habits/quran",
                {"date": today, "juz": juz, "pages": pages, "note": note or None},
            )
            await ctx.send(f"📖 Quran logged ({result['local_date']}): juz={juz}, pages={pages}.")
        except Exception as exc:
            await ctx.send(f"Failed to log Quran progress: {str(exc)[:180]}")

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
                embed.set_footer(text=f"prayer:{item['prayer_date']}:{item['prayer_name']}")
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
        try:
            _, prayer_date, prayer_name = footer.split(":")
        except Exception:
            return

        status = PRAYER_EMOJI_TO_STATUS[emoji]
        payload_data = {
            "prayer_date": prayer_date,
            "prayer_name": prayer_name,
            "status": status,
            "source": "discord_reaction",
            "discord_user_id": str(payload.user_id),
        }
        try:
            await api_post("/prayer/checkin", payload_data)
            await channel.send(f"Logged `{prayer_name}` for {prayer_date}: {status}.")
        except Exception as exc:
            await channel.send(f"Failed to log prayer check-in: {str(exc)[:200]}")


async def setup(bot):
    await bot.add_cog(RemindersCog(bot))
