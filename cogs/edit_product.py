import asyncpg
import uuid
import disnake
from disnake.ext import commands
from utils.database import get_database_pool
from utils.permissions import is_authorized
import config
import logging

logger = logging.getLogger(__name__)


class EditProduct(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(
        description="Edit the name or role of an existing product (owner or permitted roles).",
    )
    async def edit_product(self, inter: disnake.ApplicationCommandInteraction):
        if not await is_authorized(inter, "edit_product"):
            return

        async with (await get_database_pool()).acquire() as conn:
            rows = await conn.fetch(
                "SELECT product_name, role_id FROM products WHERE guild_id = $1 ORDER BY product_name",
                str(inter.guild.id)
            )

        if not rows:
            await inter.response.send_message(
                "❌ No products found. Add one first with `/add_product`.",
                ephemeral=True,
                delete_after=config.message_timeout
            )
            return

        options = [
            disnake.SelectOption(label=row["product_name"])
            for row in rows
        ]

        view = ProductPickerView(inter.guild, options)
        await inter.response.send_message(
            "Select a product to edit:",
            view=view,
            ephemeral=True
        )
        view.message = await inter.original_message()


class ProductPickerView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, options: list):
        super().__init__(timeout=120)
        self.guild = guild
        dropdown = disnake.ui.StringSelect(
            placeholder="Choose a product",
            options=options[:25]
        )
        dropdown.callback = self.on_select
        self.add_item(dropdown)
        self.message = None

    async def on_select(self, interaction: disnake.MessageInteraction):
        product_name = interaction.data["values"][0]
        await interaction.response.edit_message(
            content=f"Editing **{product_name}** — choose what to change:",
            view=EditOptionsView(self.guild, product_name)
        )

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="❌ Session timed out. Run the command again.", view=None)
            except (disnake.NotFound, disnake.Forbidden):
                pass


class EditOptionsView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, product_name: str):
        super().__init__(timeout=120)
        self.guild = guild
        self.product_name = product_name

    @disnake.ui.role_select(
        placeholder="Assign a different role (type to search)",
        min_values=1,
        max_values=1,
        row=0
    )
    async def role_select(self, select: disnake.ui.RoleSelect, interaction: disnake.MessageInteraction):
        await interaction.response.defer()
        self.stop()
        await self._save_role(interaction, select.values[0])

    @disnake.ui.button(
        label="Create New Role Automatically",
        style=disnake.ButtonStyle.success,
        row=1
    )
    async def auto_create(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        await interaction.response.defer()
        self.stop()
        role_name = f"Verified-{self.product_name}"
        try:
            role = await self.guild.create_role(name=role_name, reason="KeyVerify role edit")
        except disnake.Forbidden:
            await interaction.edit_original_message(
                content="❌ I don't have permission to create roles.", view=None
            )
            return
        await self._save_role(interaction, role)

    @disnake.ui.button(
        label="Rename Product",
        style=disnake.ButtonStyle.secondary,
        row=1
    )
    async def rename(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        self.stop()
        await interaction.response.send_modal(RenameProductModal(self.guild, self.product_name))

    async def _save_role(self, interaction: disnake.MessageInteraction, role: disnake.Role):
        try:
            async with (await get_database_pool()).acquire() as conn:
                await conn.execute(
                    "UPDATE products SET role_id = $1 WHERE guild_id = $2 AND product_name = $3",
                    str(role.id), str(self.guild.id), self.product_name
                )
        except asyncpg.PostgresError as e:
            logger.error(f"[DB Error] Failed to update role for '{self.product_name}' in '{self.guild.name}': {e}")
            await interaction.edit_original_message(
                content="❌ Failed to save role update. Please try again.",
                view=None
            )
            return

        logger.info(f"[Role Updated] '{self.product_name}' in '{self.guild.name}' → role '{role.name}'")

        bot_top_role = self.guild.me.top_role
        hierarchy_warning = (
            f"\n\n⚠️ The bot's role is below **{role.name}** in the server hierarchy. "
            f"Move **{bot_top_role.name}** above **{role.name}** in Server Settings → Roles."
        ) if role >= bot_top_role else ""

        await interaction.edit_original_message(
            content=f"✅ Role for **{self.product_name}** updated to {role.mention}.{hierarchy_warning}",
            view=None
        )


class RenameProductModal(disnake.ui.Modal):
    def __init__(self, guild: disnake.Guild, current_name: str):
        self.guild = guild
        self.current_name = current_name
        components = [
            disnake.ui.TextInput(
                label="New Product Name",
                custom_id="new_name",
                value=current_name,
                style=disnake.TextInputStyle.short,
                max_length=100,
            )
        ]
        # Unique per instance — static modal custom_ids collide in disnake's modal store.
        super().__init__(title="Rename Product", custom_id=f"rename_product_modal:{uuid.uuid4().hex[:12]}", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        new_name = interaction.text_values["new_name"].strip()

        if not new_name:
            await interaction.response.send_message(
                "❌ Product name cannot be empty.", ephemeral=True, delete_after=config.message_timeout
            )
            return

        if new_name == self.current_name:
            await interaction.response.send_message(
                "❌ The name is the same as the current one.", ephemeral=True, delete_after=config.message_timeout
            )
            return

        try:
            async with (await get_database_pool()).acquire() as conn:
                existing = await conn.fetchrow(
                    "SELECT 1 FROM products WHERE guild_id = $1 AND product_name = $2",
                    str(self.guild.id), new_name
                )
                if existing:
                    await interaction.response.send_message(
                        f"❌ A product named **`{new_name}`** already exists.",
                        ephemeral=True,
                        delete_after=config.message_timeout
                    )
                    return

                await conn.execute(
                    "UPDATE products SET product_name = $1 WHERE guild_id = $2 AND product_name = $3",
                    new_name, str(self.guild.id), self.current_name
                )
                await conn.execute(
                    "UPDATE verified_licenses SET product_name = $1 WHERE guild_id = $2 AND product_name = $3",
                    new_name, str(self.guild.id), self.current_name
                )
        except asyncpg.PostgresError as e:
            logger.error(f"[DB Error] Failed to rename '{self.current_name}' → '{new_name}' in '{self.guild.name}': {e}")
            await interaction.response.send_message(
                "❌ Failed to rename product. Please try again.",
                ephemeral=True,
                delete_after=config.message_timeout
            )
            return

        logger.info(f"[Product Renamed] '{self.current_name}' → '{new_name}' in '{self.guild.name}'")
        await interaction.response.send_message(
            f"✅ Product renamed from **`{self.current_name}`** to **`{new_name}`**.",
            ephemeral=True,
            delete_after=config.message_timeout
        )


def setup(bot):
    bot.add_cog(EditProduct(bot))
