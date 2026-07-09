import discord
from discord import app_commands
import config

def _has_permission(member: discord.Member, operation: str = "ec_admin") -> bool:
    if member.guild_permissions.administrator:
        return True
    allowed_role_ids = set(config.OPERATION_ROLES.get(operation, []))
    user_role_ids = {role.id for role in member.roles}
    return bool(allowed_role_ids.intersection(user_role_ids))

def require_clearance(operation: str = "ec_admin", guild_only: bool = True):
    def predicate(interaction: discord.Interaction) -> bool:
        if guild_only and interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        return _has_permission(interaction.user, operation)
    return app_commands.check(predicate)