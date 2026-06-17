"""Command-line entry point for Tau."""

from pathlib import Path
from typing import Annotated

import anyio
import typer

from tau_agent import (
    AgentEndEvent,
    AgentEvent,
    AgentHarness,
    AgentHarnessConfig,
    ErrorEvent,
    MessageDeltaEvent,
    MessageEndEvent,
    MessageStartEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from tau_ai import ModelProvider, OpenAICompatibleProvider, openai_compatible_config_from_env
from tau_coding import __version__, create_coding_tools, load_skills
from tau_coding.system_prompt import BuildSystemPromptOptions, build_system_prompt

DEFAULT_MODEL = "gpt-4.1-mini"

app = typer.Typer(
    name="tau",
    help="Tau coding-agent harness.",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
    prompt_arg: Annotated[
        str | None,
        typer.Argument(help="Prompt to run in non-interactive print mode."),
    ] = None,
    prompt_option: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Prompt to run in non-interactive print mode."),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Model name to request from the provider."),
    ] = DEFAULT_MODEL,
    cwd: Annotated[
        Path | None,
        typer.Option("--cwd", help="Working directory for built-in coding tools."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show Tau's version and exit."),
    ] = False,
) -> None:
    """Run the Tau CLI."""
    if version:
        typer.echo(f"tau {__version__}")
        raise typer.Exit()

    prompt = prompt_option or prompt_arg
    if not prompt:
        typer.echo("Tau print mode is installed. Pass a prompt or run `tau --version`.")
        raise typer.Exit()

    try:
        ok = anyio.run(run_openai_print_mode, prompt, model, cwd or Path.cwd())
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not ok:
        raise typer.Exit(1)


async def run_openai_print_mode(prompt: str, model: str, cwd: Path) -> bool:
    """Run print mode with the OpenAI-compatible provider configured from the environment."""
    provider = OpenAICompatibleProvider(openai_compatible_config_from_env())
    try:
        return await run_print_mode(prompt=prompt, model=model, cwd=cwd, provider=provider)
    finally:
        await provider.aclose()


async def run_print_mode(
    *,
    prompt: str,
    model: str,
    cwd: Path,
    provider: ModelProvider,
) -> bool:
    """Run one non-interactive prompt and print streamed events.

    Returns False when the agent emits a non-recoverable error so CLI callers
    can fail non-interactive runs while still rendering the error message.
    """
    tools = create_coding_tools(cwd=cwd)
    skills = load_skills()
    system = build_system_prompt(BuildSystemPromptOptions(cwd=cwd, tools=tools, skills=skills))
    harness = AgentHarness(
        AgentHarnessConfig(
            provider=provider,
            model=model,
            system=system,
            tools=tools,
        )
    )
    renderer = PrintModeRenderer()
    async for event in harness.prompt(prompt):
        renderer.render(event)
    return not renderer.failed


class PrintModeRenderer:
    """Small event renderer for non-interactive CLI output."""

    def __init__(self) -> None:
        self._assistant_started = False
        self._assistant_ended = False
        self.failed = False

    def render(self, event: AgentEvent) -> None:
        if isinstance(event, MessageStartEvent):
            self._assistant_started = False
            self._assistant_ended = False
            return

        if isinstance(event, MessageDeltaEvent):
            self._assistant_started = True
            typer.echo(event.delta, nl=False)
            return

        if isinstance(event, ToolExecutionStartEvent):
            self._ensure_assistant_newline()
            typer.echo(f"→ {event.tool_call.name} {event.tool_call.arguments}", err=True)
            return

        if isinstance(event, ToolExecutionEndEvent):
            status = "✓" if event.result.ok else "✗"
            typer.echo(f"{status} {event.result.name}", err=True)
            if not event.result.ok and event.result.content:
                typer.echo(event.result.content, err=True)
            return

        if isinstance(event, ErrorEvent):
            if not event.recoverable:
                self.failed = True
            self._ensure_assistant_newline()
            typer.echo(f"Error: {event.message}", err=True)
            return

        if isinstance(event, MessageEndEvent | AgentEndEvent):
            self._ensure_assistant_newline(final=True)

    def _ensure_assistant_newline(self, *, final: bool = False) -> None:
        if self._assistant_started and not self._assistant_ended:
            typer.echo()
            self._assistant_ended = True
        elif final and not self._assistant_started:
            self._assistant_ended = True
