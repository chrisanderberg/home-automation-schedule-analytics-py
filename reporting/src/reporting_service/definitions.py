"""Dagster definitions wiring for reporting assets, schedules, and sensors."""

from dagster import Definitions, ScheduleDefinition, define_asset_job

from reporting_service.assets import (
    snapshot_sensor,
    snapshot_summary,
    testing_api_snapshot_validation,
    testing_snapshot_summary,
)

snapshot_job = define_asset_job("snapshot_job", selection=["snapshot_summary"])
testing_snapshot_job = define_asset_job("testing_snapshot_job", selection=["testing_snapshot_summary"])
testing_api_flow_job = define_asset_job("testing_api_flow_job", selection=["testing_api_snapshot_validation"])

snapshot_schedule = ScheduleDefinition(job=snapshot_job, cron_schedule="0 2 * * *")

definitions = Definitions(
    assets=[snapshot_summary, testing_snapshot_summary, testing_api_snapshot_validation],
    schedules=[snapshot_schedule],
    sensors=[snapshot_sensor],
    jobs=[snapshot_job, testing_snapshot_job, testing_api_flow_job],
)
