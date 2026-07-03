import uuid
import disnake
from disnake.ext import commands
import config
import logging
from utils.database import save_feedback
from utils.permissions import is_authorized

logger = logging.getLogger(__name__)


class FeedbackModal(disnake.ui.Modal):
    # The form the user fills in: a short subject plus a free-text body.
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Subject",
                custom_id="subject",
                placeholder="A short summary (e.g. 'Idea: bulk product import')",
                style=disnake.TextInputStyle.short,
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Feedback or suggestion",
                custom_id="message",
                placeholder="Describe your idea, feedback, or the issue in detail…",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            ),
        ]
        # Unique per instance — static modal custom_ids collide in disnake's modal store.
        super().__init__(title="Send Feedback", custom_id=f"feedback_modal:{uuid.uuid4().hex[:12]}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        subject = inter.text_values["subject"].strip()
        message = inter.text_values["message"].strip()

        try:
            await save_feedback(
                inter.guild.id, inter.guild.name,
                inter.author.id, str(inter.author),
                subject, message,
            )
        except Exception:
            logger.exception(f"[Feedback] Failed to save feedback from {inter.author}")
            await inter.response.send_message(
                "❌ Couldn't save your feedback right now. Please try again later.",
                ephemeral=True,
                delete_after=config.message_timeout,
            )
            return

        logger.info(f"[Feedback] {inter.author} submitted feedback in '{inter.guild.name}'")
        await inter.response.send_message(
            "✅ Thanks! Your feedback has been sent to the developer.",
            ephemeral=True,
            delete_after=config.message_timeout,
        )


class Feedback(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # No default_member_permissions: is_authorized() is the real gate so the owner can
    # delegate "send_feedback" to roles without granting any server-wide Discord permission.
    @commands.slash_command(
        description="Send feedback or a suggestion to the developer (owner or permitted roles).",
    )
    async def feedback(self, inter: disnake.ApplicationCommandInteraction):
        if not await is_authorized(inter, "send_feedback"):
            return

        await inter.response.send_modal(FeedbackModal())


def setup(bot):
    bot.add_cog(Feedback(bot))
