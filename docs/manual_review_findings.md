# Manual Review Findings

This document records the manual evaluation of anomaly events produced from the
January 15, 2024 AIS dataset. It is a living review document and will be updated
as each detector is evaluated.

An automated alert means that a record met a detector's rule. It does not, by
itself, prove suspicious behavior.

## Evaluation method

The combined output contains 3,367 events belonging to 1,822 unique vessels.
Because loitering accounts for most events, the review sample is deliberately
balanced rather than proportional:

- 6 loitering events
- 5 signal-gap events
- 4 unusual-port-behavior events
- 4 speed-inconsistency events

The sample is intended to compare detector behavior and expose edge cases. It
is not an unbiased estimate of accuracy across all 3,367 events.

## Cross-detector overlap checkpoint

- 1,710 vessels triggered one detector type during the day.
- 108 vessels triggered two detector types during the day.
- 4 vessels triggered three detector types during the day.
- 82 vessels had different detector types that overlapped or occurred within
  two hours.
- Of those 82 vessels, 81 had exactly two connected detector types and one had
  three connected detector types.
- Loitering plus signal gap was the strongest connected pair, with 71 vessels
  and 23.91% normalized overlap.

Time proximity creates a stronger candidate relationship, but it does not prove
that alerts describe suspicious behavior. Multiple detectors can react to the
same unreliable AIS record.

## Loitering review

The six selected events cover the 60-minute rule boundary, medium and long
durations, near-port boundary cases, missing or stale navigation status, and an
explicit operational status.

| Vessel | Key evidence | Preliminary interpretation |
| --- | --- | --- |
| ERICA LYNN | Exactly 60 minutes, median 0.3 knots, 70.9 km from Key West | Needs more context |
| SEKCO | 512 minutes, 439 pings, median 0 knots, 67.0 km from Lake Charles | Likely normal or operational |
| ELIN MERRITT | 1,200 minutes, 1,029 pings, median 0.1 knot | Likely normal or operational |
| KELLY MORRISON | Almost 24 hours stationary while status said under way | Needs more context; status may be stale |
| MISS JUANITA | Almost 24 hours stationary, only 31.8 km from port | Likely normal or a port-distance threshold artifact |
| HOS WARLAND | Almost 24 hours stationary, 31.9 km from port, restricted maneuverability | Likely normal or operational |

### Loitering conclusion

The detector reliably identifies vessels that remain slow or stationary for at
least one hour outside the configured 30 km port radius. The available evidence
does not reliably explain why they were stationary.

The review exposed three likely sources of false positives:

1. Events exactly at the 60-minute duration threshold.
2. Vessels barely outside the 30 km port boundary.
3. Legitimate stationary operations indicated by navigation status or vessel
   context.

For example, HAFNIA LUPUS was classified as open-water loitering at 30.005455 km
from port, only about 5.5 metres beyond the cutoff, while reporting `at_anchor`.
This is a clear threshold artifact even though the code applied the configured
rule correctly.

The current loitering rule answers, "Which vessels remained slow offshore?" It
does not yet answer, "Which vessels remained slow offshore for a suspicious
reason?"

## Review status

- Loitering: reviewed
- Signal gap: pending
- Unusual port behavior: pending
- Speed inconsistency: pending

