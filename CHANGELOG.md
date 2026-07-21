# Changelog

## Unreleased - framework hardening

### Added

- Named synchronous, background, and awaited command execution modes.
- A bounded FIFO error queue, lifecycle/fail-safe hooks, and deterministic task cleanup.
- Stdio, stream, UART, and in-memory transport boundaries with ordered response serialization.
- A documented and tested common-command/status-register model.
- Atomic command-map construction with alias provenance and collision diagnostics.
- CPython regression coverage for the host-testable framework behavior.
- An authoritative instrument-subclass contract covering construction, handlers, tasks, reset, status, and safety hooks.

### Changed

- Query handlers return values; the dispatcher owns response framing and transport writes.
- Boolean, integer, float, and enum conversion now consistently validates SCPI input.
- ADC acquisition starts disabled, and EOF terminates the command loop cleanly.
- Numeric command-header suffixes are documented as unsupported unless literally declared.

### Fixed

- Async mode ambiguity, leaked task failures, reset/shutdown races, and empty program-message units.
- Error-queue ordering and status/event-register clearing, latching, and summary behavior.
- Duplicate short/long aliases, optional-command collisions, and unsafe inherited command replacement.
- Relative parsing fallback, which could previously discard an unknown leading command node.
- `*OPC` and `*OPC?` waiting on persistent underscore-prefixed system tasks.

Pico hardware smoke testing and memory-growth evidence remain outstanding before a tagged release.
