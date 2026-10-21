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
- Signal gap: reviewed
- Unusual port behavior: reviewed
- Speed inconsistency: reviewed

## Signal-gap review

Signal gaps were the strongest source of behavioral review candidates, but gap
duration alone was not enough to rank them. WEST AURIGA disappeared for 14.9
hours and reappeared at the same coordinates with low endpoint speeds. That
pattern is more consistent with an equipment, receiver-coverage, or source-data
interruption than concealed travel.

KATHRYN disappeared for 19.9 hours and reappeared 525.6 km away. Its implied
average speed was 14.3 knots, closely matching the reported endpoint speeds of
13.4 and 13.9 knots. ZIM NINGBO and ONE CONTRIBUTION showed similar physically
plausible open-water travel during long reporting absences.

| Vessel | Key evidence | Verdict |
| --- | --- | --- |
| WEST AURIGA | 14.9-hour gap, identical endpoints, low speeds | Data quality / reporting availability |
| PGC MARINA | 10-hour gap, 18.6 km movement, open-to-port | Needs context |
| ONE CONTRIBUTION | 14.3-hour open-water gap, 402.0 km movement | Investigation-worthy |
| ZIM NINGBO | 15.3-hour far-offshore gap, 510.7 km movement at plausible speed | Investigation-worthy |
| KATHRYN | 19.9-hour open-water gap, 525.6 km movement at plausible speed | Investigation-worthy |

### Signal-gap conclusion

A stronger signal-gap candidate combines a long reporting absence, open-water
endpoints, substantial movement, and an implied speed consistent with reported
speeds. This supports additional review but does not prove intentional AIS
shutdown.

## Unusual-port-behavior review

The current rule uses a flat 30 km port radius. Three of four reviewed events
looked like ordinary passage or threshold effects rather than meaningful port
behavior. LOU ANNA GUIDRY reported 40-51 knots across only three pings, making
unreliable position or identity data more plausible than a valid port event.

| Vessel | Key evidence | Verdict |
| --- | --- | --- |
| LOU ANNA GUIDRY | 3 pings, 3-minute event, 40-51 knots | Data quality |
| HOS CROCKETT | Steady 9-knot transit through a broad coastal zone | Likely normal |
| ALL IN | Continued moving near the outer edge of the 30 km zone | Likely normal |
| PRINCESS IVY | 28-29 km from port and just above the 2-knot slowdown cutoff | Likely normal |

### Unusual-port conclusion

The rule applies its thresholds correctly, but circular port zones do not model
real harbor approaches. Future refinement should use port polygons, entrance
geometry, heading, and speed-change patterns.

## Speed-inconsistency review

All four reviewed speed events were physically impossible or directly
contradicted reported vessel speed. The detector provides valuable protection
against corrupt coordinates, mixed identities, or synthetic data, but its
outputs belong in a data-quality lane rather than behavioral risk.

| Vessel | Key evidence | Verdict |
| --- | --- | --- |
| ADRIATIC | 103.3-knot implied speed versus 22.8-knot reported maximum | Data quality |
| GAN EDEN | 565.2 km in 11.9 minutes, implying 1,540.9 knots | Data quality |
| AN ANGEL | 1,882.2 km in 14.5 minutes while reporting 5.8 knots | Data quality |
| VIEW | 4,423.4 km in 5.7 minutes, sequential-looking MMSI | Data quality |

## Overall manual-review result

| Verdict | Reviewed events |
| --- | ---: |
| Investigation-worthy | 3 |
| Data quality | 6 |
| Likely normal | 7 |
| Needs context | 3 |

The pipeline is useful as a screening system, but 3,367 automated events must
not be presented as 3,367 suspicious incidents. The evaluated product has three
distinct analysis lanes: behavioral review, data quality, and operational
context. The next evaluation should use more days and a larger labeled sample
before estimating detector precision.

