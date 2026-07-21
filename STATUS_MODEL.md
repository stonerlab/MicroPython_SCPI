# Supported SCPI status model

This framework implements a deliberately small, tested subset of IEEE 488.2 and SCPI status behavior:

```text
operation/questionable condition
    -> positive transition event latch
    -> enable mask
    -> status-byte summary bit
    -> service-request enable mask
    -> MSS/RQS bit

standard event latch -> event-status enable -> ESB summary --+
error queue -------------------------------> error summary --+-> SRE -> MSS/RQS
```

## Registers and bits

- Operation and questionable condition registers are 15-bit values. A zero-to-one transition latches the corresponding event bit. Negative-transition filters are not implemented.
- Reading an operation or questionable event register returns and clears that latch. The condition register is unchanged.
- The Standard Event Status Register is an 8-bit latch. `*ESR?` returns and clears it. `*ESE` selects which latched bits assert ESB, status-byte bit 5.
- A non-empty error queue asserts status-byte bit 2. Questionable and operation summaries use bits 3 and 7 respectively.
- `*SRE` selects status-byte sources into bit 6, MSS/RQS. Bit 6 is a derived result, so writes to SRE bit 6 are ignored and `*SRE?` reports it cleared.
- Every event read, enable write, error-queue change, `*CLS`, and `STATus:PRESet` recomputes summary and service-request state.

## Common-command behavior

- `*CLS` clears the error queue and all event latches. It preserves condition registers and enable masks and does not manufacture transition events.
- `STATus:PRESet` clears operation/questionable event latches and their enable masks. It preserves condition registers, standard-event state, ESE/SRE, errors, and application tasks.
- `*RST` awaits cancellation and cleanup of non-system application tasks, resets operation/questionable conditions, and performs `*CLS`.
- `*OPC` waits for earlier application tasks and then latches Standard Event bit 0. `*OPC?` waits and returns `1` without changing that latch.
- The self-test common command is implemented as the query `*TST?`.

This is not a claim of complete IEEE 488.2 or SCPI-1999 conformance. In particular, positive/negative transition filter commands, output-queue/MAV behavior, and a physical service-request line are outside the implemented subset.
