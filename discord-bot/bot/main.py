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


@bot.event
async def setup_hook():
    for cog in ["bot.cogs.agents", "bot.cogs.approvals", "bot.cogs.health", "bot.cogs.reminders"]:
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
async def custom_help(ctx):
    embed = discord.Embed(title="LifeOS Commands", description="Discord-first control surface", color=0x2563EB)
    embed.add_field(
        name="Agent",
        value=(
            "`!ask <agent> <message>`\n"
            "`!sandbox <message>`\n"
            "`!agents`\n"
            "`!daily` `!weekly`\n"
            "`!today` `!focus`\n"
            "`!profile`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Chat Sessions",
        value=(
            "`!sessions <agent>`\n"
            "`!newsession <agent> [title]`\n"
            "`!usesession <agent> <session_id>`\n"
            "`!renamesession <agent> <session_id> <title>`\n"
            "`!clearsession <agent> [session_id]`\n"
            "`!history <agent> [session_id]`\n"
            "Tip: `!ask` auto-uses your active session per channel."
        ),
        inline=False,
    )
    embed.add_field(
        name="Life",
        value=(
            "`!add <domain> <text>`\n"
            "`!done <id> [note]`\n"
            "`!miss <id> [note]`\n"
            "`!prayertoday` `!prayerlog <date> <prayer> <status>`\n"
            "`!quran <juz> [pages]` `!tahajjud <done|missed> [date]`\n"
            "`!adhkar <morning|evening> <done|missed> [date]`\n"
            "domains: deen, family, work, health, planning"
        ),
        inline=False,
    )
    embed.add_field(
        name="Approvals",
        value="`!pending` `!approve <id>` `!reject <id> [reason]`",
        inline=False,
    )
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
