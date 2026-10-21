# Step 1: Load Data and Count Events and Unique Vessels

from pathlib import Path
from itertools import combinations

import pandas as pd


# Locate the completed output from the anomaly pipeline

EVENTS_PATH = Path("data/processed/anomaly_events.csv")

# Stop with a clear message if the pipeline output is unavailable
if not EVENTS_PATH.exists():
    raise FileNotFoundError(
        f"Anomaly events file not found at {EVENTS_PATH}. "
        "Please run the anomaly detection pipeline first."
    )

# Load the anomaly events data
events_df = pd.read_csv(EVENTS_PATH)

#Count event rows.
event_count = len(events_df)

# Count distinct vessel identifiers
unique_vessels_count = events_df["MMSI"].nunique()

print("INVESTIGATION STEP 1")
print(f"Event rows: {event_count:,}")
print(f"Unique vessels: {unique_vessels_count:,}")

# Step 2: Count events per detector

event_counts = events_df["anomaly_type"].value_counts()

#Step 2B: Count unique vessels per detector

vessel_counts = (
    events_df.groupby("anomaly_type")["MMSI"]
    .nunique()
    .sort_values(ascending=False)
)

print("\nINVESTIGATION STEP 2")
print("\nEvent counts per detector:")
print(event_counts)

print("\nUnique vessel counts per detector:")
print(vessel_counts)

# Step 2C: Compare results and ratios 

detector_comparison = pd.DataFrame(
    {
        "events": event_counts,
        "vessels": vessel_counts,
    }
)


# Calculate the average events per vessel.
detector_comparison["events_per_vessel"] = (
    detector_comparison["events"]
    / detector_comparison["vessels"]
)


# Round the average to two decimal places.
detector_comparison["events_per_vessel"] = (
    detector_comparison["events_per_vessel"].round(2)
)


print("\nComplete detector comparison:")
print(detector_comparison) 


# Step 3A: Count how many detector types each vessel triggered.
rules_per_vessel = (
    events_df.groupby("MMSI")["anomaly_type"]
    .nunique()
)


# Step 3B: Count how many vessels triggered each number of detectors.
rule_count_distribution = (
    rules_per_vessel
    .value_counts()
    .sort_index()
)


# Step 3C: Turn the counts into a comparison table.
rule_count_table = pd.DataFrame(
    {
        "vessels": rule_count_distribution
    }
)


# Calculate each group's percentage of all flagged vessels.
rule_count_table["percentage"] = (
    rule_count_table["vessels"]
    / rule_count_table["vessels"].sum()
    * 100
).round(2)


# Give the index a descriptive name.
rule_count_table.index.name = "detector_types"


print("\nINVESTIGATION STEP 3")
print("\nNumber of detector types triggered per vessel:")
print(rule_count_table)


#Step 4A: Count how many vessels triggered each pair of detectors.

vessels_per_detector_pair = {
    detector: set(detector_rows["MMSI"])
    for detector, detector_rows 
    in events_df.groupby("anomaly_type")
}

print("\nINVESTIGATION STEP 4")
print("\nSame vessel, any time - detector pairs:")

detector_names = sorted(vessels_per_detector_pair.keys())

for left_detector, right_detector in combinations(detector_names, 2):
    left_vessels = vessels_per_detector_pair[left_detector]
    right_vessels = vessels_per_detector_pair[right_detector]

    shared_vessels = left_vessels & right_vessels

    #Use the smaller detector group as the denominator for the percentage calculation.
    smaller_group_size = min(len(left_vessels), len(right_vessels))

    #Calculate the normalized overlap percentage

    normalized_overlap_percentage = (
        len(shared_vessels) / smaller_group_size * 100
    )


    print(
        f"{left_detector} + {right_detector}: "
        f"{len(shared_vessels)} shared vessels, "
        f"{normalized_overlap_percentage:.2f}% normalized overlap"
    )
    
   


# Step 5A: Convert timestamp text into datetime values.
events_df["start_time"] = pd.to_datetime(
    events_df["start_time"],
    errors="raise",
)

events_df["end_time"] = pd.to_datetime(
    events_df["end_time"],
    errors="raise",
)


# Events separated by two hours or less may be connected.
time_tolerance = pd.Timedelta(hours=2)


print("\nINVESTIGATION STEP 5A")
print(f"Start-time data type: {events_df['start_time'].dtype}")
print(f"End-time data type:   {events_df['end_time'].dtype}")
print(f"Time tolerance:       {time_tolerance}")


# Step 5B: Determine whether two event windows are connected.
def events_are_connected(
    left_start,
    left_end,
    right_start,
    right_end,
    tolerance,
):
    return (
        left_start <= right_end + tolerance
        and right_start <= left_end + tolerance
    )


# Example 1: The events overlap.
example_1 = events_are_connected(
    pd.Timestamp("2024-01-15 10:00:00"),
    pd.Timestamp("2024-01-15 12:00:00"),
    pd.Timestamp("2024-01-15 11:00:00"),
    pd.Timestamp("2024-01-15 13:00:00"),
    time_tolerance,
)


# Example 2: The second event starts 90 minutes later.
example_2 = events_are_connected(
    pd.Timestamp("2024-01-15 10:00:00"),
    pd.Timestamp("2024-01-15 12:00:00"),
    pd.Timestamp("2024-01-15 13:30:00"),
    pd.Timestamp("2024-01-15 15:00:00"),
    time_tolerance,
)


# Example 3: The second event starts four hours later.
example_3 = events_are_connected(
    pd.Timestamp("2024-01-15 10:00:00"),
    pd.Timestamp("2024-01-15 12:00:00"),
    pd.Timestamp("2024-01-15 16:00:00"),
    pd.Timestamp("2024-01-15 17:00:00"),
    time_tolerance,
)


print("\nINVESTIGATION STEP 5B")
print(f"Overlapping events:           {example_1}")
print(f"Events separated by 90 min:   {example_2}")
print(f"Events separated by 4 hours:  {example_3}")


# Step 5C: Store connected detector pairs and their vessels.
connected_vessels_by_pair = {}

connected_rules_by_vessel = {}


# Process one vessel at a time.
for mmsi, vessel_events in events_df.groupby("MMSI"):

    # Put this vessel's events in chronological order.
    vessel_events = vessel_events.sort_values("start_time")

    # Convert the rows into dictionaries for easier pair comparison.
    event_records = vessel_events.to_dict("records")

    # Compare every event with every event after it.
    for left_index, left_event in enumerate(event_records):
        for right_event in event_records[left_index + 1:]:

            # We only want events produced by different detectors.
            if left_event["anomaly_type"] == right_event["anomaly_type"]:
                continue

            connected = events_are_connected(
                left_event["start_time"],
                left_event["end_time"],
                right_event["start_time"],
                right_event["end_time"],
                time_tolerance,
            )

            # Ignore event pairs that are more than two hours apart.
            if not connected:
                continue

            # Sort the detector names so each pair has one consistent order.
            detector_pair = tuple(
                sorted(
                    [
                        left_event["anomaly_type"],
                        right_event["anomaly_type"],
                    ]
                )
            )

            # Record this MMSI under its connected detector pair.
            connected_vessels_by_pair.setdefault(
                detector_pair,
                set(),
            ).add(mmsi)

            # Record all connected detector types for this vessel.
            connected_rules_by_vessel.setdefault(
                mmsi,
                set(),
            ).update(detector_pair)


print("\nINVESTIGATION STEP 5C")
print(
    "Vessels with time-connected detector types: "
    f"{len(connected_rules_by_vessel):,}"
)


# Step 5D: Count connected detector types for each connected vessel.
connected_detector_counts = pd.Series(
    {
        mmsi: len(detector_types)
        for mmsi, detector_types
        in connected_rules_by_vessel.items()
    }
)


vessels_with_two_connected_rules = (
    connected_detector_counts == 2
).sum()

vessels_with_three_or_more_connected_rules = (
    connected_detector_counts >= 3
).sum()

vessels_without_a_connected_pair = (
    unique_vessels_count
    - len(connected_detector_counts)
)

print("\nINVESTIGATION STEP 5D")
print(
    "No time-connected detector pair: "
    f"{vessels_without_a_connected_pair:,}"
)
print(
    "Exactly 2 connected detector types: "
    f"{vessels_with_two_connected_rules:,}"
)
print(
    "3+ connected detector types: "
    f"{vessels_with_three_or_more_connected_rules:,}"
)


# Step 5E: Display the connected detector-pair results.

print("\nINVESTIGATION STEP 5E")
print("\nSame vessel, within two hours - detector pairs:")


for left_detector, right_detector in combinations(detector_names, 2):
    detector_pair = tuple(
        sorted(
            [
                left_detector,
                right_detector,
            ]
        )
    )

    # Obtain the connected vessels for this pair.
    # Return an empty set if the pair had no connected vessels.
    shared_vessels = connected_vessels_by_pair.get(
        detector_pair,
        set(),
    )

    left_vessels = vessels_per_detector_pair[left_detector]
    right_vessels = vessels_per_detector_pair[right_detector]

    smaller_detector_count = min(
        len(left_vessels),
        len(right_vessels),
    )

    normalized_overlap = (
        len(shared_vessels)
        / smaller_detector_count
        * 100
    )

    print(
        f"{left_detector} + {right_detector}: "
        f"{len(shared_vessels)} connected vessels, "
        f"{normalized_overlap:.2f}% normalized overlap"
    )


    # Step 6: Display each time-connected multi-detector vessel.

print("\nINVESTIGATION STEP 6")
print("\nTime-connected multi-detector vessels:")


for mmsi in sorted(connected_rules_by_vessel):
    vessel_rows = events_df[
        events_df["MMSI"] == mmsi
    ]

    vessel_names = (
        vessel_rows["vessel_name"]
        .dropna()
        .astype(str)
    )

    if vessel_names.empty:
        vessel_name = "Unknown"
    else:
        vessel_name = vessel_names.iloc[0]

    connected_detectors = sorted(
        connected_rules_by_vessel[mmsi]
    )

    detector_text = ", ".join(connected_detectors)

    print(
        f"{mmsi} | "
        f"{vessel_name} | "
        f"{detector_text}"
    )



    # Step 7A: Define the detailed output file for each detector.

detector_files = {
    "loitering": Path(
        "data/processed/loitering_events.csv"
    ),
    "signal_gap": Path(
        "data/processed/signal_gap_events.csv"
    ),
    "unusual_port_behavior": Path(
        "data/processed/unusual_port_behavior_events.csv"
    ),
    "speed_inconsistency": Path(
        "data/processed/speed_inconsistency_events.csv"
    ),
}


# Define the desired number of review events per detector.
sample_sizes = {
    "loitering": 6,
    "signal_gap": 5,
    "unusual_port_behavior": 4,
    "speed_inconsistency": 4,
}


# Load each detailed detector output.
detector_data = {
    detector: pd.read_csv(file_path)
    for detector, file_path in detector_files.items()
}


print("\nINVESTIGATION STEP 7A")
print("\nDetailed detector files:")


for detector, detector_df in detector_data.items():
    requested_rows = sample_sizes[detector]

    print(
        f"{detector}: "
        f"{len(detector_df):,} available events, "
        f"{requested_rows} requested for review"
    )


print(
    "Total requested review events: "
    f"{sum(sample_sizes.values())}"
)



# Step 7B: Inspect loitering candidates.

loitering_df = detector_data["loitering"]


loitering_review_columns = [
    "MMSI",
    "vessel_name",
    "duration_minutes",
    "candidate_ping_count",
    "median_sog",
    "primary_status_label",
    "nearest_port",
    "median_port_distance_km",
    "suspicion_level",
]


# Events closest to the minimum 60-minute threshold.
shortest_loitering = (
    loitering_df
    .sort_values("duration_minutes")
    [loitering_review_columns]
    .head(10)
)


# Events with the longest durations.
longest_loitering = (
    loitering_df
    .sort_values(
        "duration_minutes",
        ascending=False,
    )
    [loitering_review_columns]
    .head(10)
)


# Events closest to the 30 km port-distance boundary.
boundary_loitering = (
    loitering_df
    .sort_values("median_port_distance_km")
    [loitering_review_columns]
    .head(10)
)


print("\nINVESTIGATION STEP 7B")

print("\nShortest loitering events:")
print(shortest_loitering.to_string(index=False))

print("\nLongest loitering events:")
print(longest_loitering.to_string(index=False))

print("\nLoitering events closest to the port boundary:")
print(boundary_loitering.to_string(index=False))



# Step 7C: Select six deliberately varied loitering events.

loitering_review_mmsis = [
    367148620,  # ERICA LYNN
    367508280,  # SEKCO
    368161910,  # ELIN MERRITT
    367072840,  # KELLY MORRISON
    367001890,  # MISS JUANITA
    367643740,  # HOS WARLAND
]


selected_loitering_rows = []


for mmsi in loitering_review_mmsis:
    matching_events = loitering_df[
        loitering_df["MMSI"] == mmsi
    ]

    if matching_events.empty:
        raise ValueError(
            f"Loitering event not found for MMSI {mmsi}"
        )

    selected_loitering_rows.append(
        matching_events.iloc[0]
    )


loitering_sample = pd.DataFrame(
    selected_loitering_rows
)


print("\nINVESTIGATION STEP 7C")
print("\nSelected loitering review events:")

print(
    loitering_sample[
        loitering_review_columns
    ].to_string(index=False)
)

print(
    f"\nSelected loitering rows: "
    f"{len(loitering_sample)}"
)


# Step 7D: Inspect different kinds of signal gaps.

signal_gap_df = detector_data["signal_gap"]


signal_gap_review_columns = [
    "MMSI",
    "VesselName",
    "gap_minutes",
    "gap_distance_km",
    "previous_port_distance_km",
    "port_distance_km",
    "endpoint_context",
    "previous_sog",
    "SOG",
    "windspeed_kmh",
    "visibility_m",
    "suspicion_level",
]


smallest_movement_gaps = (
    signal_gap_df
    .sort_values("gap_distance_km")
    [signal_gap_review_columns]
    .head(5)
)


largest_movement_gaps = (
    signal_gap_df
    .sort_values(
        "gap_distance_km",
        ascending=False,
    )
    [signal_gap_review_columns]
    .head(5)
)


longest_signal_gaps = (
    signal_gap_df
    .sort_values(
        "gap_minutes",
        ascending=False,
    )
    [signal_gap_review_columns]
    .head(5)
)


print("\nINVESTIGATION STEP 7D")

print("\nSignal gaps by endpoint context:")
print(signal_gap_df["endpoint_context"].value_counts())

print("\nSignal gaps with the smallest movement:")
print(smallest_movement_gaps.to_string(index=False))

print("\nSignal gaps with the largest movement:")
print(largest_movement_gaps.to_string(index=False))

print("\nLongest signal gaps:")
print(longest_signal_gaps.to_string(index=False))
