"""Airflow DAG for the maritime anomaly detection pipeline.

This learning version contains the first eight pipeline tasks. The combined
event table and final verification will be added in the next chunk.
"""

# datetime gives Airflow a timezone-aware date for this DAG.
from datetime import datetime, timezone

# DAG is Airflow's object for describing a workflow and its settings.
from airflow.sdk import DAG

# BashOperator creates a task that runs one shell command on an Airflow worker.
from airflow.providers.standard.operators.bash import BashOperator


# The with block groups every task inside it into this one DAG.
with DAG(
    # dag_id is the permanent name shown in the Airflow web UI.
    dag_id="maritime_anomaly_pipeline",
    # This description explains the DAG's purpose in the UI.
    description="Clean, enrich, and analyze NOAA AIS vessel data.",
    # start_date is required metadata for Airflow's scheduling model.
    start_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
    # schedule=None means this learning version runs only when manually triggered.
    schedule=None,
    # catchup=False prevents Airflow from creating historical scheduled runs.
    catchup=False,
    # Only one DAG run may execute at a time, protecting shared output files.
    max_active_runs=1,
    # Tags make the DAG easier to find in the Airflow UI.
    tags=["maritime", "anomaly-detection"],
) as dag:
    # This is the first task in the DAG.
    clean_ais = BashOperator(
        # task_id is the task's unique name inside this DAG.
        task_id="clean_ais",
        # The worker runs the same cleaning script already proven in the container.
        bash_command="python /opt/airflow/src/validation/clean_ais.py",
        # Use the mounted project root as the command's working directory.
        cwd="/opt/airflow",
    )

    # This second task adds nearest-port information to the cleaned AIS data.
    join_ports = BashOperator(
        task_id="join_ports",
        bash_command="python /opt/airflow/src/fusion/join_ports.py",
        cwd="/opt/airflow",
    )

    # Detect loitering episodes from the fused AIS and port-proximity data.
    detect_loitering = BashOperator(
        task_id="detect_loitering",
        bash_command="python /opt/airflow/src/anomaly_rules/loitering.py",
        cwd="/opt/airflow",
    )

    # Detect MMSIs that broadcast conflicting vessel identities.
    detect_identity_inconsistency = BashOperator(
        task_id="detect_identity_inconsistency",
        bash_command=(
            "python /opt/airflow/src/anomaly_rules/identity_inconsistency.py"
        ),
        cwd="/opt/airflow",
    )

    # Detect physically implausible movement between consecutive AIS positions.
    detect_speed_inconsistency = BashOperator(
        task_id="detect_speed_inconsistency",
        bash_command="python /opt/airflow/src/anomaly_rules/speed_inconsistency.py",
        cwd="/opt/airflow",
    )

    # Detect vessels that disappear from AIS and later return.
    detect_signal_gaps = BashOperator(
        task_id="detect_signal_gaps",
        bash_command="python /opt/airflow/src/anomaly_rules/signal_gaps.py",
        cwd="/opt/airflow",
    )

    # Add weather observations to the signal-gap events produced above.
    add_weather_context = BashOperator(
        task_id="add_weather_context",
        bash_command="python /opt/airflow/src/fusion/add_weather_context.py",
        cwd="/opt/airflow",
    )

    # Detect unusual short visits through port zones.
    detect_unusual_port_behavior = BashOperator(
        task_id="detect_unusual_port_behavior",
        bash_command=(
            "python /opt/airflow/src/anomaly_rules/unusual_port_behavior.py"
        ),
        cwd="/opt/airflow",
    )

    # Each >> arrow means the task on the right waits for the task on the left.
    # This order exactly matches PIPELINE_STEPS in src/pipeline/run_phase3.py.
    (
        clean_ais
        >> join_ports
        >> detect_loitering
        >> detect_identity_inconsistency
        >> detect_speed_inconsistency
        >> detect_signal_gaps
        >> add_weather_context
        >> detect_unusual_port_behavior
    )
