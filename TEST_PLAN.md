# TEST_PLAN.md

## Purpose
- Track the post-initial-PR test expansion work.
- Distinguish what is now implemented from the smaller set of remaining gaps.

## Current Status
- Shared logic: `45` tests passing.
- Aggregation: `36` tests passing.
- Reporting: `30` tests passing.
- Live socket integration tests are implemented and run in a normal local environment.
- In restricted/sandboxed environments, the live socket tests self-skip when local port binding is not permitted.

## Implemented

### shared-logic
Target file: `shared-logic/tests/test_ingest.py`

- [x] `test_holding_ingest_updates_expected_blob_bucket_counts`
- [x] `test_transition_ingest_updates_expected_transition_counts`
- [x] `test_holding_ingest_splits_across_multiple_quarter_rows`
- [x] `test_ingest_holding_rejects_unknown_control`
- [x] `test_ingest_holding_rejects_state_out_of_range`
- [x] `test_ingest_transition_rejects_unknown_control`
- [x] `test_ingest_transition_rejects_state_out_of_range`
- [x] `test_ingest_transition_rejects_self_transition`
- [x] `test_ingest_skips_undefined_clock_calculations_without_failing`

Target file: `shared-logic/tests/test_storage.py`

- [x] `test_upsert_and_get_control_roundtrip_with_state_labels`
- [x] `test_get_control_raises_not_found_for_missing_control`
- [x] `test_update_aggregate_rolls_back_when_update_fn_raises`
- [x] `test_update_aggregate_rejects_blob_size_mismatch`
- [x] `test_update_aggregate_creates_row_for_existing_control`
- [x] `test_init_schema_migrates_legacy_aggregates_table_with_foreign_key`
- [x] `test_init_schema_drops_orphaned_aggregate_rows_during_migration`

Target file: `shared-logic/tests/test_snapshot.py`

- [x] `test_export_snapshot_creates_readable_sqlite_copy`
- [x] `test_export_snapshot_for_test_uses_deterministic_filename`
- [x] `test_export_snapshot_for_test_rejects_path_separators`
- [x] `test_export_snapshot_for_test_rejects_empty_name_components`
- [x] `test_reset_test_db_files_removes_db_and_sidecars`
- [x] `test_backup_to_path_cleans_up_temp_file_when_replace_fails`
- [x] `test_backup_to_path_cleans_up_temp_file_when_backup_fails`

Target file: `shared-logic/tests/test_paths.py`

- [x] `test_test_data_root_defaults_to_repo_test_data_directory`
- [x] `test_test_data_root_honors_test_data_dir_override`
- [x] `test_test_data_root_rejects_missing_override_directory`
- [x] `test_test_snapshot_root_uses_test_data_root`
- [x] `test_repository_root_finds_repo_from_module_path`
- [x] `test_repository_root_finds_repo_from_current_working_directory`
- [x] `test_find_repo_root_from_real_tree_returns_none_when_sentinel_missing`

Target file: `shared-logic/tests/test_blob.py`

- [x] `test_blob_constructor_rejects_invalid_raw_length`
- [x] `test_hold_index_rejects_out_of_range_state`
- [x] `test_transition_index_rejects_out_of_range_state`
- [x] `test_blob_roundtrip_with_max_supported_state_count`

Target file: `shared-logic/tests/test_quarter.py`

- [x] `test_quarter_index_exact_boundary_start_of_quarter`
- [x] `test_split_interval_exactly_ends_on_quarter_boundary`
- [x] `test_split_interval_exactly_starts_on_quarter_boundary`

### aggregation
Target file: `aggregation/tests/test_api.py`

- [x] `test_main_transition_endpoint_accepts_valid_payload`
- [x] `test_main_snapshot_endpoint_exports_snapshot_file`
- [x] `test_testing_snapshot_endpoint_exports_named_snapshot_file`
- [x] `test_testing_reset_endpoint_removes_test_database`
- [x] `test_main_controls_rejects_unknown_fields`
- [x] `test_main_controls_rejects_missing_required_fields`
- [x] `test_main_controls_rejects_bool_for_num_states`
- [x] `test_main_controls_rejects_invalid_state_labels_length`
- [x] `test_main_holding_rejects_unknown_control`
- [x] `test_main_holding_rejects_invalid_json_body`
- [x] `test_main_holding_rejects_non_json_content_type`
- [x] `test_main_transition_rejects_self_transition`
- [x] `test_main_transition_rejects_bool_for_timestamp`
- [x] `test_testing_endpoints_require_slug_test_name_consistently`
- [x] `test_testing_flow_reset_create_ingest_snapshot_produces_expected_sqlite_contents`

Target file: `aggregation/tests/test_jsonio.py`

- [x] `test_decode_strict_json_accepts_valid_object`
- [x] `test_decode_strict_json_rejects_non_json_content_type`
- [x] `test_decode_strict_json_rejects_malformed_json`
- [x] `test_decode_strict_json_rejects_non_object_payload`
- [x] `test_decode_strict_json_rejects_missing_required_fields`
- [x] `test_decode_strict_json_rejects_unknown_fields`

Target file: `aggregation/tests/test_main_runtime.py`

- [x] `test_load_config_requires_latitude_and_longitude`
- [x] `test_load_config_rejects_non_numeric_latitude_longitude`
- [x] `test_load_config_rejects_out_of_range_latitude`
- [x] `test_load_config_rejects_out_of_range_longitude`
- [x] `test_load_ports_rejects_non_numeric_main_port`
- [x] `test_load_ports_rejects_out_of_range_testing_port`
- [x] `test_load_bind_hosts_rejects_unresolvable_host`
- [x] `test_create_server_controller_wraps_permission_denied`
- [x] `test_server_controller_stop_is_idempotent`
- [x] `test_server_controller_should_run_returns_false_after_request_stop`
- [x] `test_server_controller_should_run_returns_false_when_thread_dies`

Target file: `aggregation/tests/test_integration_runtime.py`

- [x] `test_dual_server_runtime_serves_main_and_testing_health_endpoints`
- [x] `test_testing_runtime_flow_exports_snapshot_with_expected_contents`

### reporting
Target file: `reporting/tests/test_definitions_and_assets.py`

- [x] `test_snapshot_summary_reads_counts_from_real_snapshot`
- [x] `test_testing_snapshot_summary_reads_counts_from_real_snapshot`
- [x] `test_testing_api_flow_succeeds_with_valid_snapshot`
- [x] `test_testing_api_flow_fails_when_snapshot_file_missing_after_export`
- [x] `test_testing_api_flow_fails_when_snapshot_is_corrupt`
- [x] `test_testing_api_flow_fails_when_snapshot_has_too_few_controls`
- [x] `test_testing_api_flow_fails_when_snapshot_has_too_few_aggregates`
- [x] `test_post_json_returns_error_payload_for_http_error_response`
- [x] `test_post_json_returns_sanitized_error_payload_for_empty_http_error_body`
- [x] `test_post_json_returns_sanitized_error_payload_for_malformed_http_error_body`
- [x] `test_post_json_handles_non_dict_success_payload`
- [x] `test_latest_snapshot_path_in_dir_selects_newest_sqlite_file`
- [x] `test_snapshot_sensor_emits_run_request_for_new_snapshot`
- [x] `test_snapshot_sensor_skips_when_cursor_is_current`
- [x] `test_snapshot_sensor_skips_when_snapshot_removed`
- [x] `test_snapshot_sensor_tolerates_invalid_cursor_value`
- [x] Selected `Failure.metadata` assertions for key Dagster failure paths

Target file: `reporting/tests/test_http_json.py`

- [x] `test_decode_invalid_multiline_payload_compacts_whitespace`
- [x] `test_decode_invalid_whitespace_only_body_returns_unparseable_payload`

Target file: `reporting/tests/test_integration_asset_flow.py`

- [x] `test_testing_api_snapshot_can_be_consumed_by_reporting_asset_flow`

Target file: `reporting/tests/test_integration_main_snapshot_summary.py`

- [x] `test_main_api_snapshot_can_be_summarized_by_reporting_asset`

## Remaining Gaps

### lower priority
- [ ] Add even broader log/metadata assertions for additional Dagster failure cases beyond the key ones already covered.
- [ ] Decide whether the remaining test output noise is acceptable or whether to suppress more logger paths.

## Notes
- Prefer assertions on exact sqlite contents and blob counters over row-count-only smoke checks.
- Keep most tests tempfile-backed and isolated from `data/`.
- Keep Flask contract tests at test-client level unless socket behavior is the thing being verified.
- Live socket tests are intentionally written to skip when the environment blocks local binds.
