# Instrument subclass contract

This document is the authoritative contract for classes built on `Instrument` or `SCPI`. It describes requirements imposed by
the dispatcher and lifecycle code, including requirements that Python cannot express with abstract methods.

## Choose the correct base class

- Subclass `SCPI` for a device exposed as a SCPI instrument. It supplies the tested common commands, error queue, and status
  model.
- Subclass `Instrument` directly only for a command protocol that deliberately does not expose the framework's SCPI common and
  status commands.
- Keep one `Instrument`/`SCPI` lineage. `BuildCommands` copies one inherited command map and does not support combining command
  maps through multiple inheritance.
- Set the class attribute `version` to the device firmware/interface version reported by `*IDN?`. A string is recommended.

Every concrete class that declares commands must be decorated with `@BuildCommands` after its methods have been decorated with
`@Command`:

```python
from instr import AWAITED, BuildCommands, Command, SCPI


@BuildCommands
class PowerSupply(SCPI):
    version = "1.0.0"

    @Command(command="MEASure:VOLTage?")
    def measure_voltage(self):
        return self.read_voltage()

    @Command(command="CALibrate?", async_call=AWAITED)
    async def calibrate(self):
        await self.run_calibration()
        return 0
```

## Construction and framework-owned state

A subclass constructor must call `super().__init__(...)` exactly once. A reusable subclass should accept `**kwargs` and forward
them so callers retain access to `debug`, `error_queue_capacity`, lifecycle callbacks, transports, and
`legacy_print_handlers`:

```python
def __init__(self, *, spi=None, **kwargs):
    self.spi = spi
    super().__init__(**kwargs)
```

Hardware dependencies may be prepared before the call, but framework tasks must be started only after it: `super()` creates the
task registry, lock, error queue, transport state, and status state. The constructor should leave outputs in a safe, inactive
state. If construction can fail after energising hardware, the board application remains responsible for cleanup.

The following names are framework-owned and must not be replaced by application data: `command_map`, names beginning `_scpi_`,
`tasks`, `lock`, `error_q`, `current_node`, `stb`, `_active_transport`, and the `_oper_*`, `_ques_*`, `_event_*`, and
`_service_*` status fields. Use the documented properties and helpers instead of mutating their backing fields.

## Command declarations and handler signatures

- The mixed-case `command` spelling defines the SCPI grammar: uppercase letters form the short alias, the full uppercased word is
  the long alias, colons separate nodes, square brackets generate optional variants, and `?` marks a query.
- Numeric suffixes are not inferred. Declare a literal digit in the header or, preferably, model a channel as a converted
  parameter.
- `parameters` must contain one callable converter for every command argument, in order. The framework requires the exact count;
  optional parameters and variadic handler arguments are not supported.
- After conversion, the handler receives `self` followed by exactly those converted values. Converters should return a value,
  raise an `SCPIError` for a specific protocol failure, or raise `TypeError`/`ValueError` to produce `DataTypeError`.
- Expected device or input failures should raise an appropriate `SCPIError`. Other exceptions are treated as unexpected failures:
  they invoke the safety/diagnostic policy and enqueue one `CommandExecutionError`.
- Synchronous handlers must finish quickly because they block input and the event loop.

`BuildCommands` rejects ambiguous short/long aliases, optional expansions, and inherited collisions atomically. A subclass can
override behavior in either of these supported ways:

1. Override the same Python method name without another `@Command`; the inherited command metadata and execution mode remain in
   force, so the replacement signature and sync/async behavior must remain compatible.
2. Decorate a handler for the same complete canonical command. It may use a different Python method name and replaces that
   inherited command in the subclass map.

Changing the command attached to an inherited Python method name is rejected. Adding new commands to a parent after a child class
was built does not update the existing child's copied command map.

## Execution modes and query responses

Use `SYNC`, `BACKGROUND`, or `AWAITED` explicitly:

- `SYNC`: the handler is an ordinary function and must not return an awaitable.
- `BACKGROUND`: the handler must return an awaitable. Its result is ignored, and the framework records and monitors its task.
- `AWAITED`: the handler must return an awaitable and command processing waits for its result while other scheduled work may run.

An async query must use `AWAITED`; queries cannot use `BACKGROUND` because responses would be reordered. Decorator inference makes
an async function `BACKGROUND`, so async queries always need the explicit mode.

A query handler returns its response. It must not print to stdout or write directly to the active transport. The dispatcher owns
serialization, locking, and line framing: booleans become `0`/`1`, bytes are decoded, `None` becomes an empty response, and other
values use `str(value)`. Return values from non-query commands are ignored. `legacy_print_handlers=True` is a temporary stdio-only
migration mode, not a contract for new handlers.

## Background work, cancellation, and reset

Start device-owned background work with `_start_task(name, awaitable)` after framework construction and while an event loop is
active. Creating tasks in `__init__` is runtime-dependent and is not portable to CPython; portable subclasses start them from an
async service context or command. A normal application task name must not start with `_`: `*RST`, `*OPC`, and `*WAI` treat
underscore-prefixed tasks as persistent framework/system work. The top-level `run()` service cancels all tasks, including system
tasks, when it exits.

Long-running handlers and tasks must yield to the event loop, use `finally` for hardware cleanup, and not swallow cancellation.
Task exceptions are retrieved by the framework; an `SCPIError` enters the error queue and an unexpected exception runs the
safety/diagnostic policy.

`SCPI.reset()` is the `*RST` handler and is asynchronous. An override must remain async and must `await super().reset()` exactly
once. The override may put hardware into a safe state before that await and restore documented power-on defaults afterwards. The
base implementation:

- cancels and retrieves non-system application tasks;
- clears operation and questionable conditions;
- clears event latches and the error queue; and
- preserves the event, service-request, operation, and questionable enable masks.

An override must preserve those observable semantics. If `self_test()` is overridden, it remains synchronous unless the inherited
command metadata is explicitly and compatibly redeclared; return `0` for success and a device-defined nonzero result for failure.

## Status and errors

Device code reports current conditions through the `oper_reg` and `ques_reg` property setters. These setters implement positive-
transition latching and update summary bits. Report Standard Event Status conditions through `event_reg`, for example
`self.event_reg |= 1`. Append `SCPIError` classes or instances to `error_q`; do not maintain a second device error list.

Do not directly write the framework-managed status-byte bits: error summary (bit 2), questionable summary (bit 3), ESB (bit 5),
MSS/RQS (bit 6), or operation summary (bit 7). The framework recomputes them. Device-specific use of other bits must not claim
unsupported output-queue/MAV or service-request behavior. The complete supported semantics are in
[`STATUS_MODEL.md`](STATUS_MODEL.md).

## Safety callbacks and shutdown

Lifecycle callbacks are synchronous, should be short and allocation-light, and must not print or write a SCPI response:

- `fail_safe(command_name, exception)` disables hazardous outputs after an unexpected command/task failure. It is also the
  fallback disconnect policy and is called as `fail_safe("exit", None)` by `exit()`.
- `diagnostic_handler(command_name, exception)` records unexpected failures to a separate diagnostic sink.
- `disconnect_handler()` puts the device into its disconnected safe state when a transport reaches EOF or disconnects.

Install them through constructor arguments, `set_fail_safe()`, and `set_disconnect_handler()`. Callback exceptions are contained
and stored in `callback_error`; they do not replace the original error policy. If `exit()` is overridden for hardware cleanup, the
override must finish by calling `super().exit()`.

`run()` owns a top-level `asyncio.run()` call and is intended for the board's synchronous entry point. Code already inside an event
loop may await `read_commands()` for a complete transport session or call `process_line()` for controlled integration/testing.
Unlike `run()`, a direct `read_commands()` call does not perform final task cancellation; its caller must use a `finally` block and
`await self._cancel_tasks(include_system=True)` (or provide equivalent ownership). EOF closes that session and its transport;
reconnect/restart policy belongs to the board application.

## Subclass review checklist

- The class inherits `SCPI` unless omission of SCPI common commands is intentional, and any class declaring commands has
  `@BuildCommands`.
- `__init__` forwards framework keyword arguments, calls `super()` once, and leaves outputs safe.
- Every handler's converters, Python signature, execution mode, and query return behavior agree.
- Command aliases are collision-free; channel numbers are explicit parameters or literal declared headers.
- Background work is registered, cancellable, and cleans up hardware in `finally`.
- `reset()` awaits the base implementation and preserves common status semantics.
- Device conditions use status properties and expected errors use `SCPIError`/`error_q`.
- Fail-safe and disconnect policies disable hazardous outputs without contaminating the response stream.
