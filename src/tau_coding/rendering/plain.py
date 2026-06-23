"""Pi-style final text renderer for print mode."""

import typer
from rich.console import Console
from rich.text import Text

from tau_agent import AgentEvent, ErrorEvent, MessageEndEvent, RetryEvent


class FinalTextRenderer:
    """Render only the final assistant text after the run finishes."""

    def __init__(self) -> None:
        self._last_assistant_text = ""
        self._failed = False
        self._error_messages: list[str] = []
        self._console = Console(stderr=True, highlight=False)

    def render(self, event: AgentEvent) -> None:
        """Record events needed for final text output."""
        if isinstance(event, MessageEndEvent):
            self._last_assistant_text = event.message.content
            return

        if isinstance(event, ErrorEvent):
            if not event.recoverable:
                self._failed = True
            self._error_messages.append(event.message)
            return

        if isinstance(event, RetryEvent):
            self._console.print(Text(f"… {event.message}", style="bright_black"))

    def finish(self) -> bool:
        """Print final text or errors and return whether the run succeeded."""
        if self._failed:
            for message in self._error_messages:
                typer.echo(f"Error: {message}", err=True)
            return False

        if self._last_assistant_text:
            typer.echo(self._last_assistant_text)
        return True
