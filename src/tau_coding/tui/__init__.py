"""Textual TUI frontend for Tau coding sessions."""

from tau_coding.tui.adapter import TuiEventAdapter
from tau_coding.tui.app import TauTuiApp, run_tui_app
from tau_coding.tui.config import (
    HIGH_CONTRAST_THEME,
    TAU_DARK_THEME,
    TuiConfigError,
    TuiKeybindings,
    TuiRoleStyle,
    TuiSettings,
    TuiTheme,
    TuiThemeName,
    get_tui_theme,
    load_tui_settings,
    tui_settings_path,
)
from tau_coding.tui.state import ChatItem, TuiState
from tau_coding.tui.widgets import (
    SessionSidebar,
    TranscriptView,
    render_chat_item,
    render_session_sidebar,
)

__all__ = [
    "ChatItem",
    "TauTuiApp",
    "SessionSidebar",
    "TAU_DARK_THEME",
    "TranscriptView",
    "TuiEventAdapter",
    "TuiConfigError",
    "HIGH_CONTRAST_THEME",
    "TuiKeybindings",
    "TuiRoleStyle",
    "TuiSettings",
    "TuiTheme",
    "TuiThemeName",
    "TuiState",
    "get_tui_theme",
    "load_tui_settings",
    "render_chat_item",
    "render_session_sidebar",
    "run_tui_app",
    "tui_settings_path",
]
