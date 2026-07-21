# Migration guide

This guide covers compatibility changes introduced by the framework-hardening work after version 0.2.0.

For the complete normative extension API, including constructor, handler, task, reset, status, and safety requirements,
see [`INSTRUMENT_SUBCLASS_CONTRACT.md`](INSTRUMENT_SUBCLASS_CONTRACT.md).

## Command execution modes

Use the named `SYNC`, `BACKGROUND`, and `AWAITED` constants for `Command(async_call=...)`. The historical values `0`, `1`,
and `2` remain accepted. Query handlers must use `SYNC` or `AWAITED`; background queries are rejected because they cannot
produce an ordered response. Reset and shutdown now await task cancellation and cleanup.

## Parameter conversion

- Boolean parameters accept `ON`, `1`, `YES`, and `TRUE`, or `OFF`, `0`, `NO`, and `FALSE`.
- `Int` and `Float` enforce inclusive minimum and maximum bounds.
- `Enum` maps both long and short SCPI labels to the declared Python values.

Invalid values now consistently become SCPI parameter errors rather than leaking converter exceptions.

## Query responses and transports

Query handlers should return their response instead of printing it. The dispatcher serializes the result, appends exactly one
line ending, and writes through the configured transport. `StdioTransport` remains the default; `StreamTransport`,
`UARTTransport`, and `MemoryTransport` support other environments and deterministic tests.

For a temporary stdio-only transition, construct the instrument with `legacy_print_handlers=True`. This mode is deliberately
limited and should be removed once handlers return values.

## Errors, lifecycle, and status

The error queue is bounded and FIFO. Unexpected command failures invoke the diagnostic and fail-safe hooks and add one execution
error. EOF cleanly stops the command loop. ADC acquisition now starts disabled and must be explicitly enabled.

The implemented common-command and status-register semantics are documented in [`STATUS_MODEL.md`](STATUS_MODEL.md), including
read-to-clear event registers, enable masks, `*CLS`, `*RST`, `*OPC`, and `STATus:PRESet`.

## Command collisions and channel syntax

`BuildCommands` now rejects ambiguous short/long aliases, optional expansions, terminal aliases, and unsafe inherited changes by
raising `CommandMapCollisionError`. Construction is atomic. A subclass override is valid only when it declares the same complete
canonical command as the inherited handler.

Numeric suffixes are not inferred. Literal digits in explicitly declared headers continue to work, but new channel-oriented APIs
should model the channel as a converted parameter. Prefer `OUTPUT:LEVEL 2,50` over relying on an undeclared
`OUTPUT2:LEVEL 50` spelling.
