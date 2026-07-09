import logging
import re
from typing import Callable, Coroutine, Any, Dict, List
import discord
from discord.ext import commands
from pydantic import BaseModel, Field, ConfigDict, field_validator

from services.state_store import TypedStateStore
from utils.discord_utils import report_error

logger = logging.getLogger(__name__)


class MenuSession(BaseModel):
    session_id: str
    bot_id: str
    owner_id: int
    current_screen: str = "MAIN"
    page: int = 0
    filter_mode: str = "ALL"
    data_context: Dict[str, Any] = Field(default_factory=dict)


session_store = TypedStateStore(MenuSession, "ui_sessions")


class ButtonSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    label: str
    action: str
    payload: str | None = None
    style: int = 2
    row: int = 0
    disabled: bool = False
    url: str | None = None

    @field_validator('style', mode='before')
    @classmethod
    def _coerce_style(cls, v):
        if hasattr(v, 'value'): return v.value
        return int(v)


class ScreenSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    content: str
    embed: Any | None = None
    buttons: List[ButtonSpec] = Field(default_factory=list)


class MenuButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"m:(?P<bot>[a-z-]+):(?P<act>[a-z_]+):(?P<sid>[a-zA-Z0-9]+)(?::(?P<pld>.+))?"):
    def __init__(self, bot_id: str, action: str, session_id: str, label: str, style: int, row: int,
                 disabled: bool = False, payload: str | None = None):
        self.bot_id = bot_id[:15]
        self.action = action
        self.session_id = session_id
        self.payload = payload

        custom_id = f"m:{self.bot_id}:{action}:{session_id}"
        if payload:
            custom_id += f":{payload}"

        if len(custom_id) > 100:
            logger.error(f"Button Custom ID too long ({len(custom_id)}): {custom_id}")
            excess = len(custom_id) - 100
            custom_id = f"m:{self.bot_id}:{action}:{session_id}:{payload[:-excess]}"

        button_style = discord.ButtonStyle(style) if isinstance(style, int) else style
        super().__init__(
            discord.ui.Button(label=label, style=button_style, custom_id=custom_id, row=row, disabled=disabled))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Item, match: re.Match[str]):
        return cls(match.group("bot"), match.group("act"), match.group("sid"), item.label, item.style.value, item.row,
                   disabled=item.disabled, payload=match.group("pld"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        session = session_store.get(self.session_id)
        if session and session.owner_id != interaction.user.id:
            await interaction.response.send_message("❌ This menu session belongs to another user. Please run the command yourself.", ephemeral=True)
            return False
        return True

    async def callback(self, interaction: discord.Interaction):
        if self.action == "close_session":
            session_store.delete(self.session_id)
            try:
                if not interaction.response.is_done(): await interaction.response.defer()
                await interaction.delete_original_response()
            except:
                pass
            return

        session = session_store.get(self.session_id)
        if not session:
            return await interaction.response.send_message("❌ Session expired. Re-run the command.", ephemeral=True)

        registry = getattr(interaction.client, "menu_registry", {})
        if self.action in registry:
            try:
                await registry[self.action](interaction, session, self.payload)
            except Exception as e:
                await report_error(interaction, e, f"Action {self.action} failed")
        else:
            await interaction.response.send_message(f"❌ Unknown action: {self.action}", ephemeral=True)


def render_screen(session: MenuSession, spec: ScreenSpec) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for btn in spec.buttons:
        if btn.url:
            view.add_item(discord.ui.Button(label=btn.label, url=btn.url, row=btn.row, disabled=btn.disabled))
        else:
            view.add_item(
                MenuButton(session.bot_id, btn.action, session.session_id, btn.label, btn.style, btn.row, btn.disabled,
                           btn.payload).item)
    return view


async def update_menu_message(interaction: discord.Interaction, spec: ScreenSpec, view: discord.ui.View):
    content = re.sub(r'\[([^\]]+)\]\((?!<)(https?://[^\)]+)\)', r'[\1](<\2>)', spec.content)
    kwargs = {"content": content, "view": view}
    if spec.embed: kwargs["embed"] = spec.embed
    if interaction.response.is_done():
        await interaction.edit_original_response(**kwargs)
    else:
        await interaction.response.edit_message(**kwargs)