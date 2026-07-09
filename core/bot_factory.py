import discord
from discord.ext import commands
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ONMBot")

class ONMBot(commands.Bot):
    def __init__(self, initial_extensions: list[str], **kwargs):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(command_prefix='!', intents=intents, **kwargs)
        self.initial_extensions_list = initial_extensions

    async def setup_hook(self):
        for extension in self.initial_extensions_list:
            try:
                await self.load_extension(extension)
                logger.info(f"Loaded: {extension}")
            except commands.ExtensionNotFound:
                logger.error(f"Cog '{extension}' not found.")
            except Exception as e:
                logger.exception(f"Failed to load cog '{extension}': {e}")

        self.tree.on_error = self.on_app_command_error

        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} global application command(s).")
        except Exception as e:
            logger.exception(f"Error syncing commands: {e}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        logger.info("Bot is ready.\n------")

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.NoPrivateMessage):
            msg = "❌ This command can only be used inside a Discord server."
        elif isinstance(error, discord.app_commands.CheckFailure):
            msg = "❌ Unauthorized: You lack the required role permissions for this command."
        else:
            msg = "❌ An unexpected error occurred while running this command."
            logger.exception(f"Unhandled app command error: {error}")

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            logger.exception(f"Failed to send error message to user: {e}")


def run_bot(bot_name: str, cogs_list: list[str], token_env_var: str):
    token = os.getenv(token_env_var)
    if not token:
        token = os.getenv('DISCORD_BOT_TOKEN')

    if not token:
        logger.error(f"{token_env_var} (or DISCORD_BOT_TOKEN fallback) not found in environment.")
        sys.exit(1)

    logger.info(f"--- Starting {bot_name} ---")
    logger.debug(f"Using discord.py version: {discord.__version__}")

    bot = ONMBot(initial_extensions=cogs_list)

    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        logger.error("Failed to log in. Check if the token is correct and valid.")
    except discord.PrivilegedIntentsRequired:
        logger.error("Privileged intents (Server Members or Message Content) are not enabled.")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during bot execution: {e}")