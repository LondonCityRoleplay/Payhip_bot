import asyncio
import uuid
import disnake
from disnake.ext import commands
import aiohttp
import os
from utils.encryption import decrypt_data
from utils.database import get_database_pool
from utils.validation import validate_license_key
from utils.errors import ValidationError
from utils.permissions import is_authorized
import config
import logging

logger = logging.getLogger(__name__)


class ResetKeyModal(disnake.ui.Modal):
    def __init__(self, product_name: str, product_secret_key: str, payhip_api_key: str):
        self.product_name = product_name
        self.product_secret_key = product_secret_key
        self.payhip_api_key = payhip_api_key
        display_name = product_name if len(product_name) <= 28 else product_name[:25] + "..."
        components = [
            disnake.ui.TextInput(
                label="License Key",
                custom_id="license_key",
                placeholder="e.g. 00000-00000-00000-00000",
                style=disnake.TextInputStyle.short,
                max_length=50,
            )
        ]
        # Unique per instance — static modal custom_ids collide in disnake's modal store.
        super().__init__(title=f"Reset License: {display_name}", custom_id=f"reset_key_modal:{uuid.uuid4().hex[:12]}", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        license_key = interaction.text_values["license_key"].strip()

        try:
            license_key = validate_license_key(license_key)
        except ValidationError as e:
            await interaction.response.send_message(f"❌ {str(e)}", ephemeral=True, delete_after=config.message_timeout)
            return

        PAYHIP_RESET_USAGE_URL = "https://payhip.com/api/v2/license/decrease"
        headers = {
            "product-secret-key": self.product_secret_key,
            "payhip-api-key": self.payhip_api_key,
            "Accept-Encoding": "gzip, deflate"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    PAYHIP_RESET_USAGE_URL,
                    headers=headers,
                    data={"license_key": license_key},
                    timeout=10
                ) as response:
                    if response.status == 200:
                        logger.info(f"[Key Reset] License for '{self.product_name}' reset by {interaction.author} in '{interaction.guild.name}'.")
                        await interaction.response.send_message(
                            f"✅ License key for '{self.product_name}' has been reset successfully.",
                            ephemeral=True, delete_after=config.message_timeout
                        )
                    else:
                        body = await response.text()
                        logger.error(f"[Key Reset Failed] Status {response.status} for '{self.product_name}' by {interaction.author}. Response: {body}")
                        await interaction.response.send_message(
                            f"❌ Failed to reset the license key. Status: {response.status}",
                            ephemeral=True, delete_after=config.message_timeout
                        )

        except asyncio.TimeoutError:
            logger.error(f"[Key Reset Timeout] Request timed out for '{self.product_name}' by {interaction.author}")
            await interaction.response.send_message(
                "❌ Request timed out. Please try again later.",
                ephemeral=True, delete_after=config.message_timeout
            )
        except aiohttp.ClientError as e:
            logger.error(f"[Key Reset Error] Network error for '{self.product_name}' by {interaction.author}: {e}")
            await interaction.response.send_message(
                "❌ Unable to reset license. Please try again later.",
                ephemeral=True, delete_after=config.message_timeout
            )


class ResetKey(commands.Cog):

    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.payhip_api_key = os.getenv("PAYHIP_API_KEY")
        if not self.payhip_api_key:
            raise ValueError("PAYHIP_API_KEY is not defined in environment variables.")

    @commands.slash_command(
        description="Reset a product license key's usage count (owner or permitted roles).",
    )
    async def reset_key(
        self,
        inter: disnake.ApplicationCommandInteraction,
        product_name: str,
    ):
        if not await is_authorized(inter, "reset_key"):
            return

        async with (await get_database_pool()).acquire() as conn:
            row = await conn.fetchrow(
                "SELECT product_secret FROM products WHERE guild_id = $1 AND product_name = $2",
                str(inter.guild.id), product_name
            )

        if not row:
            await inter.response.send_message(
                f"❌ Product '{product_name}' not found.", ephemeral=True, delete_after=config.message_timeout
            )
            return

        product_secret_key = decrypt_data(row["product_secret"])
        await inter.response.send_modal(ResetKeyModal(product_name, product_secret_key, self.payhip_api_key))


def setup(bot: commands.InteractionBot):
    bot.add_cog(ResetKey(bot))
