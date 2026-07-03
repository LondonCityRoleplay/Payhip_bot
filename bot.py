import asyncio
import warnings
import disnake
from disnake.ext import commands
import os
import logging
from dotenv import load_dotenv
from utils.database import initialize_database, get_database_pool, run_auto_rotation, get_setting
from utils.logging_config import setup_logging
from utils.errors import ConfigurationError, DatabaseError
from handlers.verification_handler import VerificationButton
from bot_api import start_bot_api
import config

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

setup_logging(LOG_LEVEL)
logger = logging.getLogger(__name__)

# Disnake creates this coroutine internally during shutdown but never awaits it — harmless.
warnings.filterwarnings("ignore", message="coroutine 'AsyncWebhookAdapter.request' was never awaited")

intents = disnake.Intents.default()
intents.guilds = True
command_sync_flags = commands.CommandSyncFlags.default()
command_sync_flags.sync_commands_debug = True

class KeyVerifyBot(commands.InteractionBot):
    # disnake has no on_close event, so cleanup must live in the close() override —
    # this runs on Ctrl+C / SIGTERM before the gateway connection is torn down.
    async def close(self):
        try:
            pool = await get_database_pool()
            await pool.close()
            logger.info("Database connection closed.")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
        await super().close()


bot = KeyVerifyBot(
    intents=intents,
    command_sync_flags=command_sync_flags,
)

# Signals that the database is ready so on_ready doesn't race ahead of on_connect
_db_ready = asyncio.Event()

COG_DIR = "cogs"
for filename in os.listdir(COG_DIR):
    if filename.endswith(".py") and not filename.startswith("__"):
        cog_path = f"{COG_DIR}.{filename[:-3]}"
        try:
            bot.load_extension(cog_path)
        except Exception as e:
            # Log and continue — one bad cog should not prevent the bot from starting.
            logger.error(f"Failed to load cog '{cog_path}': {e}", exc_info=True)


@bot.event
async def on_connect():
    logger.info("Connected to Discord. Initializing database...")
    try:
        await initialize_database()
        await run_auto_rotation()
    except (ConfigurationError, DatabaseError) as e:
        logger.critical(f"Startup failed — aborting: {e}", exc_info=True)
        await bot.close()
        return
    await start_bot_api(bot)
    _db_ready.set()


@bot.event
async def on_ready():
    await _db_ready.wait()
    logger.info(f"Bot is online as {bot.user}!")
    status = await get_setting("status", f"/help | {config.version}")
    await bot.change_presence(activity=disnake.Game(name=status))

    # One global persistent view handles button clicks from every server's verification message.
    # No per-message or per-guild registration needed — guild context comes from the interaction.
    bot.add_view(VerificationButton())
    logger.info("Persistent verification button view registered.")


@bot.event
async def on_guild_join(guild: disnake.Guild):
    await _db_ready.wait()
    async with (await get_database_pool()).acquire() as conn:
        row = await conn.fetchrow(
            "SELECT guild_id FROM blacklisted_guilds WHERE guild_id = $1", str(guild.id)
        )
    if row:
        logger.warning(f"[Blacklist] Joined blacklisted guild '{guild.name}' ({guild.id}). Leaving immediately.")
        await guild.leave()


def run():
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    run()
