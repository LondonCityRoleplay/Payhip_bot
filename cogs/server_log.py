import asyncpg
import disnake
from disnake.ext import commands
from utils.database import get_database_pool
from utils.permissions import is_authorized
import config
import logging

logger = logging.getLogger(__name__)

# This cog allows a server owner to define a log channel where license verifications will be announced.
class SetLogChannel(commands.Cog):
    # Table creation lives in initialize_database() with the rest of the schema.
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(
        description="Set a channel to log successful verifications (owner or permitted roles).",
    )
    async def set_lchannel(
        self,
        inter: disnake.ApplicationCommandInteraction,
        channel: disnake.TextChannel
    ):
        # This command allows authorized members to set or update the log channel for license verification events.
        if not await is_authorized(inter, "set_log_channel"):
            return

        try:
            async with (await get_database_pool()).acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO server_log_channels (guild_id, channel_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2
                    """,
                    str(inter.guild.id), str(channel.id)
                )
        except asyncpg.PostgresError as e:
            logger.error(f"[DB Error] Failed to set log channel for guild {inter.guild.id}: {e}")
            await inter.response.send_message(
                "❌ Failed to save log channel. Please try again.",
                ephemeral=True,
                delete_after=config.message_timeout
            )
            return

        perms = channel.permissions_for(inter.guild.me)
        if not perms.send_messages or not perms.view_channel:
            await inter.response.send_message(
                f"⚠️ Log channel set to {channel.mention}, but the bot is missing permissions to post there. "
                f"Please give the bot **View Channel** and **Send Messages** access in that channel.",
                ephemeral=True,
                delete_after=config.message_timeout
            )
            return

        await inter.response.send_message(
            f"✅ Verification log channel set to {channel.mention}.",
            ephemeral=True,
            delete_after=config.message_timeout
        )

# Registers the SetLogChannel cog with the bot
def setup(bot):
    bot.add_cog(SetLogChannel(bot))
