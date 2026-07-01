# Phase 20.2: Prompt Immediacy Experiment

Phase 20.2 experiments with making submitted prompts appear in the TUI sooner
while keeping transcript rendering driven by agent events.

## What Changed

`AgentHarness.prompt()` still appends the user message to the harness-owned
transcript immediately, but `_run()` now emits the prompt's user message events
before entering the provider/tool agent loop:

```text
message_start user
message_end user
agent_start
turn_start
...
```

Previously, the harness waited for `run_agent_loop()` to emit `turn_start` and
then replayed the pending user message events. Moving the user message events to
the front gives event-authoritative UIs an earlier durable transcript boundary
for the submitted prompt.

`CodingSession.prompt()` and `CodingSession.continue_()` now yield streamed
events before awaiting message persistence for `MessageEndEvent` events:

```python
yield event
if isinstance(event, MessageEndEvent):
    persisted_count = await self._persist_messages_since(persisted_count)
```

Persistence is not moved to a background task. It remains awaited inside the
same async generator, preserving sequential session writes. The difference is
that the TUI receives and can render the message event before the JSONL append
and session-state refresh finish.

## Why

Long sessions can make persistence visibly expensive because each completed
message appends session entries and refreshes the persisted session state. When
that work happens before yielding the event, a submitted prompt may not appear
until persistence completes.

This experiment preserves event-authoritative transcript rendering while making
the event visible to the UI before persistence side effects run.

## Tradeoff

The event order remains deterministic, and persistence remains ordered, but the
durability timing changes:

- before: message persisted before the TUI saw it
- after: TUI sees the message immediately before persistence completes

If the process exits in that small window, the TUI may have displayed a message
that is not present after session reload.

## Pi Comparison

Pi's current harness persists `message_end` before notifying subscribers. This
Tau phase is therefore an intentional responsiveness experiment rather than a
straight port of Pi's durability timing.

## Tests

Focused coverage lives in:

```text
tests/test_agent_harness.py
tests/test_coding_session.py
```

The new session test uses a storage implementation that fails on append to prove
that the user `MessageEndEvent` is yielded before persistence is attempted.
