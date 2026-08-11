"""Airflow DAG for the maritime anomaly detection pipeline.

This first learning version contains only the AIS cleaning task. Later versions
will add the remaining pipeline steps after each dependency is understood.
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
    # This is the first and currently only task in the DAG.
    clean_ais = BashOperator(
        # task_id is the task's unique name inside this DAG.
        task_id="clean_ais",
        # The worker runs the same cleaning script already proven in the container.
        bash_command="python /opt/airflow/src/validation/clean_ais.py",
        # Use the mounted project root as the command's working directory.
        cwd="/opt/airflow",
    )
