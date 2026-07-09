import pytest
import discord
from unittest.mock import MagicMock
from utils.checks import _has_permission
import config


def test_has_permission_admin():
    member = MagicMock(spec=discord.Member)
    member.guild_permissions.administrator = True
    assert _has_permission(member, "ec_admin") is True


def test_has_permission_allowed_role():
    member = MagicMock(spec=discord.Member)
    member.guild_permissions.administrator = False
    role = MagicMock(spec=discord.Role)
    role.id = 12345
    member.roles = [role]

    config.OPERATION_ROLES = {"ec_admin": [12345]}
    assert _has_permission(member, "ec_admin") is True


def test_has_permission_denied():
    member = MagicMock(spec=discord.Member)
    member.guild_permissions.administrator = False
    role = MagicMock(spec=discord.Role)
    role.id = 99999
    member.roles = [role]

    config.OPERATION_ROLES = {"ec_admin": [12345]}
    assert _has_permission(member, "ec_admin") is False