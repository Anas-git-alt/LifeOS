"""LifeOS Discord bot entrypoint."""

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".venv", ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("lifeos-bot")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

HELP_TOPICS = {
    "agent": "Agent chat and workflows.\n`!ask <agent> <message>` `!sandbox <message>` `!agents` `!daily` `!weekly`",
    "sessions": (
        "Session memory controls.\n"
        "`!sessions <agent>` `!newsession <agent> [title]` `!usesession <agent> <id>`\n"
        "`!renamesession <agent> <id> <title>` `!clearsession <agent> [id]` `!history <agent> [id]`"
    ),
    "life": (
        "Life item and agenda tracking.\n"
        "`!today` `!focus` `!profile`\n"
        "`!add <domain> <text>` `!items [domain] [status]`\n"
        "`!done <id> [note]` `!miss <id> [note]` `!reopen <id>` `!goal <domain> <title>` `!goalprogress <id>`"
    ),
    "deen": (
        "Prayer and habits.\n"
        "`!prayer` `!prayertoday` `!prayerlog <YYYY-MM-DD> <prayer> <status> [note]`\n"
        "`!quran <end_page> [start_page] [note]` `!quranprogress`\n"
        "`!tahajjud <done|missed> [date]` `!adhkar <morning|evening> <done|missed> [date]`"
    ),
    "approvals": "Owner-only action queue.\n`!pending` `!approve <id>` `!reject <id> [reason]`",
    "jobs": (
        "Automation and scheduled jobs.\n"
        "`!schedule <prompt>` `!spawnagent <prompt>` `!reply <answer>`\n"
        "`!jobs [agent]` `!job <id>` `!pausejob <id>` `!resumejob <id>` `!jobruns <id> [limit]`"
    ),
    "system": "System diagnostics.\n`!status` `!providers`",
}


@bot.event
async def setup_hook():
    for cog in ["bot.cogs.agents", "bot.cogs.approvals", "bot.cogs.health", "bot.cogs.reminders", "bot.cogs.automation"]:
        try:
            await bot.load_extension(cog)
            logger.info("Loaded cog: %s", cog)
        except Exception as exc:
            logger.error("Failed to load cog %s: %s", cog, exc)


@bot.event
async def on_ready():
    logger.info("LifeOS bot online as %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Backend URL: %s", BACKEND_URL)
    if not os.getenv("DISCORD_OWNER_IDS", "").strip():
        logger.warning("DISCORD_OWNER_IDS is empty. Approval actions will be blocked.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="your goals"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Unknown command. Try `!help`.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")
    else:
        logger.error("Command error: %s", error)
        await ctx.send(f"Command error: {str(error)[:200]}")


@bot.command(name="help")
async def custom_help(ctx, *, topic: str = ""):
    topic_key = topic.strip().lower()
    if topic_key:
        details = HELP_TOPICS.get(topic_key)
        if not details:
            await ctx.send(
                "Unknown help topic. Try one of: "
                + ", ".join(sorted(HELP_TOPICS.keys()))
                + ". Example: `!help life`"
            )
            return
        embed = discord.Embed(
            title=f"LifeOS Help · {topic_key}",
            description=details,
            color=0x2563EB,
        )
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="LifeOS Commands",
        description="Use `!help <topic>` for details. Topics: agent, sessions, life, deen, approvals, jobs, system",
        color=0x2563EB,
    )
    embed.add_field(name="Agent", value="`!ask` `!sandbox` `!agents` `!daily` `!weekly`", inline=False)
    embed.add_field(name="Sessions", value="`!sessions` `!newsession` `!usesession` `!renamesession` `!clearsession` `!history`", inline=False)
    embed.add_field(name="Life", value="`!today` `!focus` `!profile` `!add` `!items` `!done` `!miss` `!reopen` `!goal` `!goalprogress`", inline=False)
    embed.add_field(name="Deen", value="`!prayer` `!prayertoday` `!prayerlog` `!quran` `!quranprogress` `!tahajjud` `!adhkar`", inline=False)
    embed.add_field(name="Approvals", value="`!pending` `!approve` `!reject`", inline=False)
    embed.add_field(name="Jobs", value="`!schedule` `!spawnagent` `!reply` `!jobs` `!job` `!pausejob` `!resumejob` `!jobruns`", inline=False)
    embed.add_field(name="System", value="`!status` `!providers`", inline=False)
    await ctx.send(embed=embed)


def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN not set in environment")
        return
    bot.run(token)


if __name__ == "__main__":
    main()
