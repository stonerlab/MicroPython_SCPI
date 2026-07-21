# MicroPython_SCPI framework improvement brief

## Purpose

This document is a self-contained implementation brief for a coding agent
working on [`stonerlab/MicroPython_SCPI`](https://github.com/stonerlab/MicroPython_SCPI).
It records framework defects and maintainability problems found while designing
the MDX 500 controller firmware. It is deliberately separate from the MDX
hardware and application specifications: every change described here should be
useful to other SCPI instruments.

The reviewed baseline is:

- repository: `stonerlab/MicroPython_SCPI`;
- branch: `main`;
- commit: `6d45b87bc95d7ee22f6261d7238267ac067119ac` (2023-11-05);
- package version: `0.2.0`.

Confirm each issue against the current upstream head before changing it. Source
locations below refer to the pinned baseline.

## Outcome required

Produce a small, testable SCPI framework that:

- dispatches synchronous, awaited-asynchronous, and background commands
  correctly;
- converts and bounds-checks command parameters predictably;
- never loses a command-task exception silently;
- implements a bounded FIFO SCPI error queue;
- can distinguish a transport disconnect from an empty command;
- does not allow unsolicited output to corrupt the SCPI response stream;
- provides internally consistent IEEE 488.2/SCPI status behavior;
- remains practical on a Raspberry Pi Pico running MicroPython;
- retains a compatibility path for existing applications using `print()`-based
  handlers and `Instrument.run()`.

This is not a request for a complete SCPI-1999 parser rewrite. Fix confirmed
correctness and safety problems first, then improve the boundaries around the
parser, transport, and application.

## Priority summary

| ID | Priority | Area | Confirmed issue | Principal consequence |
|---|---:|---|---|---|
| F-01 | P0 | dispatch | Automatic async detection tests for a `generator` instance, not an async function | Async handlers can be called without `await` and never run |
| F-02 | P0 | task handling | Completed task results/exceptions are never retrieved | Hardware/application failures disappear from SCPI |
| F-03 | P0 | runtime | Example `main.py` catches every exception and does nothing | Boot/runtime failures are hidden; fail-safe action is impossible |
| F-04 | P0 | transport | EOF is treated like another empty line | Tight retry loop after USB/serial disconnect |
| F-05 | P1 | conversion | Built-in `bool` conversion maps `OFF` and `0` to `True` | Commands can perform the opposite action requested |
| F-06 | P1 | conversion | Integer-valued `Int`/`Float` limits are ignored | Out-of-range channel and setpoint values are accepted |
| F-07 | P1 | conversion | `Enum` parses values as SCPI labels and returns labels | Positional enums fail and keyword mappings have reversed semantics |
| F-08 | P1 | status | `_qyes_event` typo leaves `_ques_event` uninitialised | Questionable-event access can raise `AttributeError` |
| F-09 | P1 | errors | Error queue uses `pop()` and is unbounded | Errors are returned newest-first and can exhaust MCU RAM |
| F-10 | P1 | dispatch | Unexpected handler exceptions escape the loop | One driver defect can terminate the command service |
| F-11 | P1 | parser | Empty program-message units reach `cmd[0]` | Leading/trailing or doubled semicolons can raise `IndexError` |
| F-12 | P1 | status | `*ESR?`, `*CLS`, `STAT:PRES`, and `*TST` semantics are inconsistent | Host status/error recovery is unreliable |
| F-13 | P2 | architecture | Input and output are hard-wired to `sys.stdin` and `print()` | Testing and use with USB/UART/TCP transports are fragile |
| F-14 | P2 | grammar | README claims numeric command suffixes, but lookup is exact | Documented channel-style commands do not work |
| F-15 | P2 | command map | Duplicate aliases silently overwrite earlier handlers | A valid command can be routed to the wrong method |
| F-16 | P2 | formatting | Engineering formatting calls `log10(0)` | Formatting zero raises an exception |

## Detailed findings and requested fixes

### F-01 — make async dispatch explicit and reliable

**Evidence:** `lib/instr/decorators.py`, `Command()`, checks
`fnc.__class__.__name__ == "generator"`. An `async def` function is a coroutine
function, not a generator instance. On the baseline,
`Command()(asyncio.sleep).async_call` is `False`. The undecorated default on the
async `SCPI.opc()` method and the README example are consequently unsafe.

**Required change:**

1. Define named execution modes rather than relying on magic values:
   synchronous, background coroutine, and awaited coroutine.
2. Preserve `async_call=0/1/2` as accepted compatibility inputs.
3. Detect coroutine functions where the runtime provides a reliable facility.
   Do not assume CPython's full `inspect` module exists in MicroPython.
4. On runtimes without reliable introspection, require an explicit async mode
   and fail clearly during class construction if a mismatch can be detected.
5. Annotate all framework async handlers explicitly, including `*OPC`,
   `*OPC?`, `*WAI`, and test-instrument sleep commands.
6. Reject a background/awaited mode applied to a non-awaitable return value
   with a controlled framework error.

**Regression tests:**

- an ordinary handler executes once synchronously;
- an awaited async handler completes before the next command is dispatched;
- a background async handler permits the next command to run;
- the default or inferred mode of every built-in async handler is correct;
- invalid mode/handler combinations produce a deterministic diagnostic;
- `*OPC` eventually sets the operation-complete event after earlier background
  work finishes.

### F-02 — retrieve and report background-task failures

**Evidence:** `Instrument.read_commands()` removes tasks whose `done()` method
is true, but never calls `result()` or otherwise retrieves an exception. Task
cleanup only occurs after processing another command.

**Required change:**

- centralise task creation in `_start_task(name, awaitable)`;
- centralise completion in `_reap_tasks()` and retrieve every task result;
- translate `SCPIError` failures directly into the error queue;
- translate other application exceptions into one documented execution error,
  retaining a debug hook/log record without exposing tracebacks on the SCPI
  stream;
- ignore normal cancellation during reset/shutdown;
- reap tasks while input is idle, not only after the next complete command;
- make it impossible to report the same task failure twice.

The application must be able to register a fail-safe callback that disables
outputs before or while a fatal task failure is reported.

**Regression tests:** successful completion, `SCPIError`, unexpected exception,
cancellation, multiple simultaneous completions, idle-time completion, and
exactly-once error reporting.

### F-03 — remove the exception-swallowing boot loop

**Evidence:** top-level `main.py` catches `Exception` and executes `pass`.

**Required change:** replace this with an explicit lifecycle:

1. initialise hardware in a safe state;
2. construct the instrument;
3. run the command service;
4. on an unexpected error, call a supplied `safe_shutdown()` hook;
5. emit the error to a diagnostic channel or preserve it for inspection;
6. restart only when an explicit restart policy says to do so, with a delay to
   avoid a tight crash loop.

Never print diagnostics into an active SCPI response stream. The example should
show where board-specific code installs the safe-shutdown hook.

### F-04 — handle EOF and disconnect without spinning

**Evidence:** `ainput()` constructs a reader, calls `readline()`, decodes it,
and loops until the stripped result is non-empty. EOF is also an empty result,
so it can loop immediately forever. CPython streams may return `str`, whereas
the function unconditionally calls `.decode()`.

**Required change:**

- construct/reuse the reader once per transport session;
- accept either `bytes` or `str` from a transport adapter;
- return or raise a distinct `TransportClosed` condition on EOF;
- yield or back off during recoverable no-data conditions;
- invoke the application's safe-disconnect policy;
- make reconnection an explicit transport responsibility.

Test both byte and text readers, blank lines, EOF before any command, EOF after
a command, and repeated reconnects without leaking readers or tasks.

### F-05 — correct boolean conversion

**Evidence:** `Executable.prep_parameters()` special-cases the built-in `bool`,
replaces `OFF`, `0`, and `NO` with the non-empty string `"False"`, then calls
`bool("False")`, which is `True`.

**Required change:** route built-in `bool` through the package's `Boolean`
converter, or remove support for built-in `bool` and raise a build-time error
that names `Boolean` as the replacement. Prefer retaining compatibility with a
correct implementation.

Test `ON`, `1`, `YES`, `TRUE`, `OFF`, `0`, `NO`, and `FALSE`, including mixed
case and surrounding whitespace. Every other token must raise `DataTypeError`.

### F-06 — enforce numeric bounds regardless of numeric type

**Evidence:** `Float.__call__()` and `Int.__call__()` enforce a bound only if
the stored limit is an instance of `float`. Therefore `Int(min=0, max=7)` and
`Float(min=0, max=7)` accept `99`.

**Required change:** treat `None` as "no bound" and compare every non-`None`
numeric bound. Validate bounds at converter construction, including `min <=
max`. Preserve inclusive endpoints. Decide and test whether booleans are valid
numeric bounds; rejecting them is less surprising.

Test integer and floating-point limits, endpoints, special `MINimum`/`MAXimum`
tokens, invalid bounds, negative values, and out-of-range errors.

### F-07 — repair `Enum` mapping semantics

**Evidence:** `Enum.__init__()` calls `prep_part(value)` and then maps the parsed
value back to `label`. Positional entries are converted to integer values, which
cannot be parsed as command text. For `Enum(POWer="power")`, `POWER` returns
`"POWer"`, not `"power"`.

**Required API:** SCPI-style labels are parsed for their short and long forms;
the associated Python value is returned. Thus:

```python
mode = Enum(POWer="power", VOLTage="voltage")
assert mode("POW") == "power"
assert mode("POWER") == "power"
```

Positional labels should either map to themselves or to documented ordinal
integers. Choose one behavior, document it, and test it. Detect duplicate short
or long aliases rather than silently replacing them.

### F-08 — initialise and name event registers consistently

**Evidence:** `SCPI.__init__()` assigns `_qyes_event`, while the
`ques_event` property reads `_ques_event`. There is also an `open_event` getter
for `_oper_event`, while command code reads `oper_event`, which currently has no
getter.

**Required change:** use `_ques_event` and provide consistently named
read-and-clear accessors for operation, questionable, and standard event
registers. Retain deprecated aliases only if existing client code needs them.
Add construction-time tests that read all registers before any event occurs.

### F-09 — implement a bounded FIFO error queue

**Evidence:** `read_error_q()` uses `self.error_q.pop()`, returning the newest
error first, and the list has no capacity limit.

**Required change:** introduce a small MicroPython-friendly queue abstraction:

- oldest error is returned first;
- capacity is configurable and has a conservative MCU default;
- when full, apply a documented SCPI-compatible overflow policy and retain an
  explicit queue-overflow error;
- `*CLS` empties the queue;
- an empty query returns `0,"No error"`;
- queue state updates the error/event status summary consistently.

Avoid depending on CPython-only `collections.deque` behavior unless a portable
fallback is included.

### F-10 — contain unexpected command exceptions

**Evidence:** the dispatch loop catches only `SCPIError`. A `ValueError`, driver
I/O exception, or programming error escapes and terminates command processing.

**Required change:** catch ordinary handler exceptions at the command boundary,
run any configured fail-safe hook, and enqueue a documented execution/device
error. Do not catch `KeyboardInterrupt`, `SystemExit`, or cancellation as normal
device errors. Debug builds may record a traceback on a separate diagnostic
sink; production SCPI output must remain parseable.

### F-11 — define empty program-message-unit behavior

**Evidence:** `parse_cmd()` indexes `cmd[0]`. Empty units produced by leading,
trailing, or repeated semicolons can therefore raise `IndexError`.

**Required change:** choose and document one policy: ignore empty units, or
enqueue a command syntax error. Apply it before parsing and ensure a whitespace-
only line is not confused with EOF. Add tests for `;CMD`, `CMD;`, `CMD;;CMD`, an
empty line, and whitespace-only input.

### F-12 — correct core status and common-command behavior

The following baseline behaviors need focused conformance work:

- `*ESR?` reports `event_reg` without clearing it. Implement read-and-clear
  Standard Event Status Register semantics.
- `*CLS` resets condition registers through their setters but does not
  explicitly clear every event latch. Clear the error queue and event latches
  without inventing new transition events.
- `STATus:PRESet` calls the full `reset()`, cancelling application tasks.
  Restrict it to the status subsystem's documented preset state.
- self-test is registered as `*TST`, although the common command is the query
  `*TST?`.
- enable and service-request masks accept arbitrary integers. Validate the
  supported bit width and reserved-bit policy.
- task cancellation by `*RST` is not awaited, so device cleanup can still be
  running after reset appears complete.

Before modifying individual bits, write a compact status model that states:

```text
condition -> transition/event latch -> enable mask -> summary bit -> service request
error queue ---------------------------------------> error summary bit
```

Then test read-and-clear behavior, enable masks, summary-bit assertion and
deassertion, `*CLS`, `STAT:PRES`, `*RST`, and `*OPC`. Do not claim full IEEE
488.2 or SCPI-1999 compliance until the implemented subset has conformance
tests.

### F-13 — separate transport, dispatch, and response generation

**Evidence:** input is hard-wired to `sys.stdin`; command handlers answer with
`print()`; handler return values are ignored. Background prints can appear in
the middle of a query response.

**Required change:** define a minimal portable transport boundary, for example:

```python
class Transport:
    async def readline(self): ...       # bytes/str, or TransportClosed
    async def write_response(self, text): ...
    async def close(self): ...
```

Query handlers should return a scalar/string (or an explicit response object),
and the dispatcher should serialize exactly one terminated response per query.
Non-query handlers should normally return no response. Provide a legacy adapter
or migration period for existing `print()` handlers, but do not redirect global
`stdout` as the long-term design.

Keep the interface allocation-light. It should support USB serial/stdin first
and allow UART or TCP adapters without changing the parser.

### F-14 — implement numeric suffixes or correct the documentation

**Evidence:** the README advertises optional numeric suffixes, but command-map
lookup at the pinned commit uses exact dictionary keys and does not extract a
suffix.

Choose one of these explicit outcomes:

1. implement suffix parsing, expose the suffix to the handler, define its
   default/range rules, and test short/long/optional forms; or
2. remove the claim and recommend an explicit channel parameter.

Do not add an ad-hoc MDX-only suffix mechanism to the general parser. Option 2
is the lower-risk compatibility release; option 1 should have a separate grammar
design and tests.

### F-15 — reject ambiguous command-map construction

**Evidence:** `BuildCommands` assigns expanded short/long aliases into nested
dictionaries without reporting when a different handler already owns an alias.

**Required change:** build into a temporary map, record command provenance, and
raise a clear class-construction error for collisions unless the subclass is an
intentional override of the same canonical command. Test optional nodes,
short-form collisions, inheritance, overrides, and monkey-patching behavior.

### F-16 — make engineering formatting total over supported inputs

**Evidence:** `Instrument.format(0)` evaluates `log10(0)` and raises. Very large,
very small, NaN, and infinite values also need defined behavior.

**Required change:** specify output for zero, negative zero, finite extremes,
NaN, and infinities. Keep engineering prefixes within the implemented table and
do not raise for a valid zero measurement. Add table-driven tests.

## Implementation progress

Change set 1 was implemented against the pinned baseline on 2026-07-21. Host regression coverage now verifies:

- F-01: named `SYNC`, `BACKGROUND`, and `AWAITED` execution modes, compatibility with numeric modes, coroutine-function inference where available, explicit modes on built-in async handlers, and controlled rejection of mode/result mismatches;
- F-05: built-in `bool` parameters use the SCPI `Boolean` converter;
- F-06: integer and floating-point bounds are validated and enforced inclusively, including integer-valued `Float` bounds, with boolean bounds rejected;
- F-07: enum labels map from SCPI short/long forms to Python values, positional labels map to themselves, and duplicate aliases are rejected;
- F-08: operation and questionable event storage/accessor names are consistent, with `open_event` retained as a compatibility alias;
- F-16: engineering formatting handles zero, negative zero, non-finite values, and finite values beyond the prefix table;
- preparatory F-15 coverage: inherited command metadata is preserved. The desired duplicate-command rejection test remains marked as an expected failure until change set 5.

The host result for this change set is `54 passed, 1 xfailed`. The expected failure is the deliberately staged F-15 collision test. Pico smoke testing remains outstanding.

Change set 2 was implemented on 2026-07-21. Host regression coverage now verifies:

- F-02: background tasks are created and reaped centrally; successful, failed, and cancelled results are retrieved exactly once, including multiple and idle-time completions;
- F-03: `main.py` uses a single explicit lifecycle, starts the ADC current source disabled, invokes safe shutdown, preserves boot/shutdown diagnostics, and has no implicit restart loop;
- F-04: one reader is reused per session, byte and text input are supported, blank input yields, EOF raises `TransportClosed`, and repeated sessions do not leak readers or tasks;
- F-09: errors use a configurable bounded FIFO with a `-350,"Queue overflow"` marker, `*CLS` clearing, the exact empty response `0,"No error"`, and automatic error-summary status updates;
- F-10: unexpected synchronous, awaited, and background failures are contained at the command boundary, invoke fail-safe/diagnostic hooks, and enqueue one execution error without catching process-control exceptions;
- F-11: empty program-message units are ignored consistently before parsing, including leading, trailing, repeated, empty, and whitespace-only forms;
- reset/shutdown task cancellation now waits for task cleanup and retrieves terminal results.

The cumulative host result after change set 2 is `83 passed, 1 xfailed`. The expected failure remains the staged F-15 collision test. Pico smoke testing remains outstanding.

## Recommended implementation sequence

Keep changes reviewable and independently releasable.

### Change set 1 — regression harness and converter correctness

- add a CPython test suite with lightweight MicroPython compatibility shims;
- fix F-01, F-05, F-06, F-07, F-08, and F-16;
- add duplicate-map tests in preparation for F-15;
- correct built-in command decorators to use explicit execution modes.

This change set should not redesign the transport.

### Change set 2 — resilient tasks, errors, and lifecycle

- implement F-02, F-03, F-04, F-09, F-10, and F-11;
- add the safe-shutdown callback and a bounded error queue;
- prove that idle background failures and disconnects are handled;
- make reset/shutdown task cleanup deterministic.

### Change set 3 — status-system correctness

- document the supported status model;
- implement and test F-12;
- update compliance claims to describe the tested subset precisely.

### Change set 4 — transport and response boundary

- implement F-13 with a stdin/USB compatibility adapter;
- migrate built-in query handlers from `print()` to return values;
- demonstrate an in-memory test transport and one MicroPython hardware
  transport;
- ensure diagnostic output cannot enter the response channel.

### Change set 5 — command grammar and documentation

- implement F-15;
- decide F-14 explicitly;
- update README examples and API reference;
- add a migration guide for changed enum/response behavior.

## Test strategy

### Host-side tests

Run fast tests on a supported desktop Python using only compatibility shims for
MicroPython-specific modules. At minimum cover:

- command-map expansion, optional nodes, inheritance, and collisions;
- parameter count, tokenization, quoting, booleans, enums, and bounds;
- synchronous, awaited, and background execution;
- task success, error, cancellation, reset, and shutdown;
- FIFO ordering and error-queue overflow;
- status-register transition, mask, summary, and read-clear behavior;
- exact response framing with an in-memory transport;
- EOF, blank lines, semicolon-separated commands, and malformed input;
- formatting edge cases.

Avoid tests that merely assert current implementation details when the desired
protocol behavior can be asserted instead.

### MicroPython/Pico tests

Run a small smoke suite on the oldest and newest supported MicroPython versions:

- import every public module within a stated RAM budget;
- build a representative instrument command map;
- process 10,000 simple commands without material memory growth;
- run and cancel background tasks repeatedly;
- disconnect and reconnect the selected USB serial transport;
- fill and drain the bounded error queue;
- verify the fail-safe callback executes after an injected handler failure;
- confirm responses remain ordered during concurrent background activity.

Record firmware version, board, free-memory before/after, and transport used.

## Compatibility requirements

- Preserve public imports from `lib.instr` unless a deprecation is documented.
- Continue accepting numeric `async_call=0`, `1`, and `2` for at least one
  compatibility release.
- Correctly interpreting `bool`, bounds, and `Enum` may change applications that
  accidentally relied on broken behavior; call this out prominently.
- Provide a transition path for `print()`-based query handlers before removing
  support.
- Keep error codes stable where already public; add new codes centrally and
  document them.
- Avoid mandatory dependencies unavailable in stock MicroPython.
- Do not allocate without bound in command processing, tasks, diagnostics, or
  error handling.

## Definition of done

The framework improvement work is complete when:

- every P0 and P1 item has a regression test and a documented resolution;
- the host test suite passes without unawaited-coroutine or unobserved-task
  warnings;
- the Pico smoke suite passes and includes memory-growth evidence;
- an unexpected application exception triggers safe shutdown and produces one
  queryable SCPI error without killing the service unintentionally;
- EOF/disconnect cannot create a busy loop;
- error ordering and status read-clear behavior are deterministic;
- query responses are transport-owned and cannot be interleaved by background
  diagnostics;
- README claims match implemented, tested command grammar;
- release notes identify compatibility changes and migration steps;
- examples contain no blanket `except Exception: pass` and start hardware in a
  fail-safe state.
