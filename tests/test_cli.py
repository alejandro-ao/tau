from pathlib import Path

import pytest
from typer.testing import CliRunner

from tau_agent import AssistantMessage
from tau_ai import (
    FakeProvider,
    ProviderErrorEvent,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderTextDeltaEvent,
)
from tau_coding import cli
from tau_coding.cli import app, run_print_mode
from tau_coding.system_prompt import BuildSystemPromptOptions, build_system_prompt
from tau_coding.tools import create_coding_tools


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "tau 0.1.0"


def test_cli_without_prompt_prints_print_mode_hint() -> None:
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0
    assert "Tau print mode is installed" in result.stdout


@pytest.mark.anyio
async def test_run_print_mode_streams_assistant_text(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderTextDeltaEvent(delta="Hel"),
                ProviderTextDeltaEvent(delta="lo"),
                ProviderResponseEndEvent(message=AssistantMessage(content="Hello")),
            ]
        ]
    )

    ok = await run_print_mode(prompt="Say hello", model="fake", cwd=tmp_path, provider=provider)

    captured = capsys.readouterr()
    assert ok is True
    assert captured.out == "Hello\n"
    assert captured.err == ""
    assert provider.calls[0][0] == "fake"
    assert provider.calls[0][1] == build_system_prompt(
        BuildSystemPromptOptions(cwd=tmp_path, tools=create_coding_tools(cwd=tmp_path))
    )
    assert [tool.name for tool in provider.calls[0][3]] == ["read", "write", "edit", "bash"]


@pytest.mark.anyio
async def test_run_print_mode_fails_on_non_recoverable_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderErrorEvent(message="provider failed"),
            ]
        ]
    )

    ok = await run_print_mode(prompt="Say hello", model="fake", cwd=tmp_path, provider=provider)

    captured = capsys.readouterr()
    assert ok is False
    assert captured.out == ""
    assert "Error: provider failed" in captured.err


def test_cli_exits_nonzero_when_print_mode_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_openai_print_mode(prompt: str, model: str, cwd: Path) -> bool:
        return False

    monkeypatch.setattr(cli, "run_openai_print_mode", fake_run_openai_print_mode)

    result = CliRunner().invoke(app, ["hello"])

    assert result.exit_code == 1
