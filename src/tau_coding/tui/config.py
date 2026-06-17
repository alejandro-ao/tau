"""Durable Textual TUI configuration for Tau."""

from dataclasses import dataclass, field
from json import loads
from pathlib import Path
from typing import Any, Literal, cast

from tau_coding.paths import TauPaths


class TuiConfigError(ValueError):
    """Raised when Tau TUI configuration is invalid."""


@dataclass(frozen=True, slots=True)
class TuiKeybindings:
    """Configurable keys for Tau's built-in Textual frontend."""

    cancel: str = "escape"
    command_palette: str = "ctrl+k"
    accept_completion: str = "tab"
    completion_next: str = "down"
    completion_previous: str = "up"
    quit: str = "ctrl+q"

    def to_json(self) -> dict[str, str]:
        """Serialize these keybindings to JSON-compatible data."""
        return {
            "cancel": self.cancel,
            "command_palette": self.command_palette,
            "accept_completion": self.accept_completion,
            "completion_next": self.completion_next,
            "completion_previous": self.completion_previous,
            "quit": self.quit,
        }


type TuiThemeName = Literal["tau-dark", "high-contrast"]


@dataclass(frozen=True, slots=True)
class TuiRoleStyle:
    """Colors for one transcript role block."""

    border: str
    body: str


@dataclass(frozen=True, slots=True)
class TuiTheme:
    """Resolved visual theme for Tau's built-in Textual frontend."""

    name: TuiThemeName
    screen_background: str
    screen_text: str
    chrome_background: str
    chrome_text: str
    muted_text: str
    sidebar_background: str
    border: str
    transcript_background: str
    prompt_background: str
    prompt_text: str
    prompt_border: str
    autocomplete_background: str
    completion_selected: str
    completion_selected_description: str
    completion_description: str
    syntax_theme: str
    role_styles: dict[str, TuiRoleStyle]


TAU_DARK_THEME = TuiTheme(
    name="tau-dark",
    screen_background="#0f1117",
    screen_text="#e6edf3",
    chrome_background="#161b22",
    chrome_text="#f0f6fc",
    muted_text="#8b949e",
    sidebar_background="#161b22",
    border="#30363d",
    transcript_background="#0d1117",
    prompt_background="#0d1117",
    prompt_text="#f0f6fc",
    prompt_border="#238636",
    autocomplete_background="#161b22",
    completion_selected="bold white on #238636",
    completion_selected_description="white on #238636",
    completion_description="bright_black",
    syntax_theme="ansi_dark",
    role_styles={
        "user": TuiRoleStyle(border="#58a6ff", body="white on #101923"),
        "assistant": TuiRoleStyle(border="#3fb950", body="white on #101f17"),
        "tool": TuiRoleStyle(border="#d29922", body="white on #201b10"),
        "error": TuiRoleStyle(border="#f85149", body="white on #241315"),
        "status": TuiRoleStyle(border="#8b949e", body="white on #161b22"),
    },
)


HIGH_CONTRAST_THEME = TuiTheme(
    name="high-contrast",
    screen_background="#000000",
    screen_text="#ffffff",
    chrome_background="#111111",
    chrome_text="#ffffff",
    muted_text="#d0d0d0",
    sidebar_background="#111111",
    border="#888888",
    transcript_background="#000000",
    prompt_background="#000000",
    prompt_text="#ffffff",
    prompt_border="#00ff66",
    autocomplete_background="#111111",
    completion_selected="bold black on #00ff66",
    completion_selected_description="black on #00ff66",
    completion_description="white",
    syntax_theme="ansi_dark",
    role_styles={
        "user": TuiRoleStyle(border="#00b7ff", body="white on #001626"),
        "assistant": TuiRoleStyle(border="#00ff66", body="white on #001a0b"),
        "tool": TuiRoleStyle(border="#ffd000", body="white on #211900"),
        "error": TuiRoleStyle(border="#ff4f4f", body="white on #260000"),
        "status": TuiRoleStyle(border="#ffffff", body="white on #111111"),
    },
)


_THEMES: dict[TuiThemeName, TuiTheme] = {
    TAU_DARK_THEME.name: TAU_DARK_THEME,
    HIGH_CONTRAST_THEME.name: HIGH_CONTRAST_THEME,
}


def get_tui_theme(name: TuiThemeName = "tau-dark") -> TuiTheme:
    """Return a built-in TUI theme by name."""
    return _THEMES[name]


@dataclass(frozen=True, slots=True)
class TuiSettings:
    """Tau TUI settings loaded from Tau home."""

    keybindings: TuiKeybindings = field(default_factory=TuiKeybindings)
    theme: TuiThemeName = "tau-dark"

    def to_json(self) -> dict[str, Any]:
        """Serialize these settings to JSON-compatible data."""
        return {
            "keybindings": self.keybindings.to_json(),
            "theme": self.theme,
        }

    @property
    def resolved_theme(self) -> TuiTheme:
        """Return the selected built-in theme."""
        return get_tui_theme(self.theme)


def tui_settings_path(paths: TauPaths | None = None) -> Path:
    """Return the durable TUI settings path."""
    return (paths or TauPaths()).home / "tui.json"


def load_tui_settings(paths: TauPaths | None = None) -> TuiSettings:
    """Load durable TUI settings, falling back to built-in defaults."""
    path = tui_settings_path(paths)
    if not path.exists():
        return TuiSettings()
    raw = loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TuiConfigError("TUI settings must be a JSON object")
    return tui_settings_from_json(raw)


def tui_settings_from_json(data: dict[str, Any]) -> TuiSettings:
    """Parse TUI settings from JSON-compatible data."""
    allowed_fields = {"keybindings", "theme"}
    unknown_fields = set(data) - allowed_fields
    if unknown_fields:
        raise TuiConfigError(f"Unknown TUI settings field: {sorted(unknown_fields)[0]}")

    keybindings_data = data.get("keybindings", {})
    if not isinstance(keybindings_data, dict):
        raise TuiConfigError("TUI keybindings must be a JSON object")
    return TuiSettings(
        keybindings=_keybindings_from_json(keybindings_data),
        theme=_theme_name(data.get("theme", "tau-dark")),
    )


def _keybindings_from_json(data: dict[str, Any]) -> TuiKeybindings:
    defaults = TuiKeybindings()
    allowed_fields = set(defaults.to_json())
    unknown_fields = set(data) - allowed_fields
    if unknown_fields:
        raise TuiConfigError(f"Unknown TUI keybinding: {sorted(unknown_fields)[0]}")

    values = {
        field_name: _key_string(data.get(field_name, default_value), field_name)
        for field_name, default_value in defaults.to_json().items()
    }
    _reject_duplicate_keys(values)
    return TuiKeybindings(**values)


def _key_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TuiConfigError(f"TUI keybinding must be a non-empty string: {field_name}")
    return value.strip()


def _theme_name(value: object) -> TuiThemeName:
    if not isinstance(value, str) or not value.strip():
        raise TuiConfigError("TUI theme must be a non-empty string")
    name = value.strip()
    if name == "tau-dark" or name == "high-contrast":
        return cast(TuiThemeName, name)
    raise TuiConfigError(f"Unknown TUI theme: {name}")


def _reject_duplicate_keys(values: dict[str, str]) -> None:
    key_to_action: dict[str, str] = {}
    for action, key in values.items():
        previous_action = key_to_action.get(key)
        if previous_action is not None:
            raise TuiConfigError(
                f"TUI keybinding {key!r} is assigned to both "
                f"{previous_action!r} and {action!r}"
            )
        key_to_action[key] = action
