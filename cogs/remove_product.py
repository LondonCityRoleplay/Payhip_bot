import disnake
from disnake.ext import commands
from utils.database import get_database_pool, fetch_product_names
from utils.permissions import is_authorized
import config
import logging

logger = logging.getLogger(__name__)

class RemoveProduct(commands.Cog):
    @commands.slash_command(
        description="Remove a product from the server's list (owner or permitted roles).",
    )
    async def remove_product(self, inter: disnake.ApplicationCommandInteraction):
        if not await is_authorized(inter, "remove_product"):
            return

        product_list = await fetch_product_names(str(inter.guild.id))
        if not product_list:
            await inter.response.send_message("❌ No products to remove.", ephemeral=True, delete_after=config.message_timeout)
            return

        # The Paginated View Class
        class PaginatorView(disnake.ui.View):
            def __init__(self, inter, items):
                super().__init__(timeout=60)
                self.inter = inter
                self.items = items
                self.page = 0
                self.max_page = (len(items) - 1) // 25
                self.dropdown = None
                self.setup_page()

            def setup_page(self):
                self.clear_items()
                
                # Slicing the list for the current page (max 25 for Discord)
                start = self.page * 25
                end = start + 25
                current_items = self.items[start:end]

                # 1. Create the Dropdown
                options = [
                    disnake.SelectOption(label=item, description=f"Remove '{item}'")
                    for item in current_items
                ]
                
                self.dropdown = disnake.ui.StringSelect(
                    placeholder=f"Select product to remove (Page {self.page + 1}/{self.max_page + 1})",
                    options=options
                )
                self.dropdown.callback = self.select_callback
                self.add_item(self.dropdown)

                # 2. Add Navigation Buttons if needed
                if self.max_page > 0:
                    prev_button = disnake.ui.Button(label="⬅️ Previous", style=disnake.ButtonStyle.gray, disabled=(self.page == 0))
                    prev_button.callback = self.prev_page
                    self.add_item(prev_button)

                    next_button = disnake.ui.Button(label="Next ➡️", style=disnake.ButtonStyle.gray, disabled=(self.page == self.max_page))
                    next_button.callback = self.next_page
                    self.add_item(next_button)

            async def prev_page(self, interaction: disnake.MessageInteraction):
                self.page -= 1
                self.setup_page()
                await interaction.response.edit_message(view=self)

            async def next_page(self, interaction: disnake.MessageInteraction):
                self.page += 1
                self.setup_page()
                await interaction.response.edit_message(view=self)

            async def select_callback(self, select_inter: disnake.MessageInteraction):
                selected = select_inter.data["values"][0]

                # Confirmation logic nested inside the selection
                class ConfirmView(disnake.ui.View):
                    def __init__(self):
                        super().__init__(timeout=30)

                    @disnake.ui.button(label="✅ Confirm", style=disnake.ButtonStyle.danger)
                    async def confirm(self, button: disnake.ui.Button, button_inter: disnake.MessageInteraction):
                        async with (await get_database_pool()).acquire() as conn:
                            result = await conn.execute(
                                "DELETE FROM products WHERE guild_id = $1 AND product_name = $2",
                                str(inter.guild.id), selected
                            )
                        
                        if result == "DELETE 0":
                            await button_inter.response.send_message(f"❌ Product '{selected}' not found.", ephemeral=True, delete_after=config.message_timeout)
                        else:
                            logger.info(f"[Delete] '{selected}' removed from '{inter.guild.name}' by {button_inter.author}")
                            await button_inter.response.send_message(f"✅ Product '{selected}' has been removed.", ephemeral=True, delete_after=config.message_timeout)
                        self.stop()

                    @disnake.ui.button(label="❌ Cancel", style=disnake.ButtonStyle.secondary)
                    async def cancel(self, button: disnake.ui.Button, button_inter: disnake.MessageInteraction):
                        await button_inter.response.send_message("Deletion cancelled 💨", ephemeral=True, delete_after=config.message_timeout)
                        self.stop()
                
                await select_inter.response.send_message(
                    f"⚠️ Are you sure you want to delete **`{selected}`**?",
                    view=ConfirmView(),
                    ephemeral=True,
                    delete_after=config.message_timeout
                )

        view = PaginatorView(inter, product_list)
        await inter.response.send_message("🗑️ Select a product to remove:", view=view, ephemeral=True)

def setup(bot):
    bot.add_cog(RemoveProduct(bot))