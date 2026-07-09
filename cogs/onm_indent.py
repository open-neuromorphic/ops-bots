import discord
from discord.ext import commands
from discord import app_commands
import uuid
import json
import logging
from pathlib import Path

import config
from models.meta import load_entity_glossary, EntityEntry, VerificationStatus
from utils.checks import require_clearance
from utils.discord_utils import report_error

logger = logging.getLogger(__name__)


class IdentityValidationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("IdentityValidationCog loaded.")

    def _save_glossary(self, glossary: dict):
        glossary_path = Path(config.META_DIR) / "entity_glossary.json"
        glossary_path.parent.mkdir(parents=True, exist_ok=True)
        # Convert entities to dicts
        out_data = {}
        for k, v in glossary.items():
            if k == "known_non_persons" or not isinstance(v, EntityEntry):
                out_data[k] = v
            else:
                out_data[k] = v.model_dump(exclude_none=True)
        glossary_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")

    def _get_or_create_entry(self, glossary: dict, discord_handle: str) -> tuple[str, EntityEntry]:
        handle_lower = discord_handle.lower()
        for key, data in glossary.items():
            if isinstance(data, EntityEntry):
                if handle_lower in [h.lower() for h in data.discord_handles]:
                    return key, data

        # Create temp entry if not found
        new_key = handle_lower.replace(" ", "_").replace(".", "_")
        new_entry = EntityEntry(discord_handles=[discord_handle])
        glossary[new_key] = new_entry
        return new_key, new_entry

    @app_commands.command(name="onm-ident-link",
                          description="Request to link a social/professional profile to your ONM identity.")
    @app_commands.describe(platform="e.g. GitHub, LinkedIn, Twitter", url="The URL to your public profile")
    async def ident_link(self, interaction: discord.Interaction, platform: str, url: str):
        try:
            glossary = load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")
            key, entry = self._get_or_create_entry(glossary, interaction.user.name)

            if entry.verification_status == VerificationStatus.VERIFIED and platform in entry.social_links:
                return await interaction.response.send_message(f"✅ Your {platform} account is already verified.",
                                                               ephemeral=True)

            token = f"ONM-VERIFY-{uuid.uuid4().hex[:6].upper()}"

            entry.verification_status = VerificationStatus.PENDING_CHALLENGE
            entry.verification_token = token
            entry.social_links[platform] = url

            self._save_glossary(glossary)

            msg = f"🔐 **Identity Linking Initiated**\n\n"
            msg += f"To securely link your `{platform}` account to your Discord identity, please follow these steps:\n"
            msg += f"1. Temporarily add this code to your `{platform}` bio/about section: **`{token}`**\n"
            msg += f"2. Notify a server Moderator (or they will see the alert).\n"
            msg += f"3. An Admin will run the `/onm-ident-verify` command to complete the link.\n"
            msg += f"4. Once verified, you may remove the code from your profile."

            await interaction.response.send_message(msg, ephemeral=True)

            # Alert mods
            guild = interaction.guild
            if guild:
                rev_channel = discord.utils.get(guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
                if rev_channel:
                    await rev_channel.send(
                        f"🔔 **Verification Request:** {interaction.user.mention} wants to link their `{platform}` account.\nURL: <{url}>\nToken: `{token}`\n*Run `/onm-ident-verify user:{interaction.user.name}` once you've checked the bio.*")

        except Exception as e:
            await report_error(interaction, e, "Failed to initiate identity link")

    @app_commands.command(name="onm-ident-verify",
                          description="Admin override to approve a pending identity challenge.")
    @app_commands.describe(member="The Discord member to verify")
    @require_clearance("ec_admin", guild_only=True)
    async def ident_verify(self, interaction: discord.Interaction, member: discord.Member):
        try:
            glossary = load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")
            handle_lower = member.name.lower()

            target_key = None
            target_entry = None
            for key, data in glossary.items():
                if isinstance(data, EntityEntry):
                    if handle_lower in [h.lower() for h in data.discord_handles]:
                        target_key = key
                        target_entry = data
                        break

            if not target_entry:
                return await interaction.response.send_message(f"❌ User `{member.name}` not found in entity glossary.",
                                                               ephemeral=True)

            if target_entry.verification_status != VerificationStatus.PENDING_CHALLENGE:
                return await interaction.response.send_message(
                    f"⚠️ User `{member.name}` does not have a pending verification challenge.", ephemeral=True)

            target_entry.verification_status = VerificationStatus.VERIFIED
            target_entry.verification_token = None

            self._save_glossary(glossary)

            await interaction.response.send_message(f"✅ Successfully verified identity links for {member.mention}.",
                                                    ephemeral=False)
        except Exception as e:
            await report_error(interaction, e, "Failed to verify identity")


async def setup(bot: commands.Bot):
    await bot.add_cog(IdentityValidationCog(bot))