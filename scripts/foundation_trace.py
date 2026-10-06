"""Actual unittest evidence and complete AT inventory, never a business score.

Run: project-python -B scripts/foundation_trace.py
The generated reports are local offline evidence. A related component test
passing does not execute a complete public business AT or a remote evaluation.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
_dialogue_spec = importlib.util.spec_from_file_location('local_dialogue_batch', ROOT/'scripts/local_dialogue_batch.py')
_dialogue_module = importlib.util.module_from_spec(_dialogue_spec)
_dialogue_spec.loader.exec_module(_dialogue_module)
trace_dialogues = _dialogue_module.trace_dialogues
_replay_spec = importlib.util.spec_from_file_location('local_replay_batch', ROOT/'scripts/local_replay_batch.py')
_replay_module = importlib.util.module_from_spec(_replay_spec)
_replay_spec.loader.exec_module(_replay_module)
_boundary_spec = importlib.util.spec_from_file_location('local_boundary_batch', ROOT/'scripts/local_boundary_batch.py')
_boundary_module = importlib.util.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
SPECIFICATION_PATHS = (
    "materials/CLASSROOM.md", "materials/client_api/openapi.yaml",
    "materials/framework/agent_contract.md", "materials/framework/client_api_contract.md",
    "materials/framework/scenario_contract.md", "materials/framework/deployment_manifest.json",
    "docs/POLICY-REGISTER.md", "docs/API-CONTRACT-MAP.md",
    "docs/PLATFORM-CONTRACT-NOTES.md", "docs/REFUND-IMPLEMENTATION-EVIDENCE.md",
)
GROUP_TESTS = {
    "G": ["test_m2_session.ReadSessionTests.test_profile_or_tool_text_is_not_independent_verification",
          "test_m2_session.ReadSessionTests.test_cross_customer_switch_and_roommate_order_are_blocked"],
    "W": ["test_m3_writes.PreflightTests.test_missing_partial_and_conditional_consent_do_not_read_or_send",
          "test_m3_completion.SessionRuntimeTests.test_stale_snapshot_extra_history_and_new_runtime_share_stable_claim",
          "test_m4_matrix.FiveEndpointMatrixTests.test_timeout_after_backend_effect_is_unknown_on_each_endpoint_without_retry",
          "test_m4_matrix.FiveEndpointMatrixTests.test_lost_tool_result_after_real_send_is_unknown_and_not_zero_send_for_all_endpoints"],
    "O": ["test_m2_reads.ReadEndpointTests.test_owned_reference_with_wrong_returned_owner_or_id_is_rejected"],
    "SEL": ["test_m3_completion.SessionRuntimeTests.test_wrong_requested_options_block_before_claim_or_http_write",
            "test_m5_candidates.CandidateSelectionTests.test_hard_stock_retention_precede_preference_and_price",
            "test_m5_candidates.CandidateSelectionTests.test_primary_tie_never_activates_fallback",
            "test_m5_candidates.CandidateSelectionTests.test_fallback_applies_its_own_change_and_relax_and_retains_other_attributes",
            "test_m5_candidates.CandidateSelectionTests.test_multiobjective_priority_max_resolution_then_cheapest_tie",
            "test_m5_candidates.CandidateSelectionTests.test_ranking_unknown_exposes_remaining_candidates_and_failed_priority_without_selection",
            "test_m5_candidates.CandidateSelectionTests.test_out_of_range_numeric_argument_and_text_measurement_have_distinct_error_channels",
            "test_m5_candidates.CandidateSelectionTests.test_excluded_unknowns_do_not_inflate_unresolved_comparison_trace",
            "test_m5_candidates.CandidateSelectionTests.test_original_price_and_size_references_use_order_not_current_source_catalog",
            "test_m5_candidates.CandidateEvidenceTests.test_assistant_text_and_future_or_stale_user_indices_are_not_request_sources",
            "test_m5_candidates.CandidateEvidenceTests.test_latest_failed_product_read_blocks_old_complete_catalog",
            "test_m5_candidates.CandidateEvidenceTests.test_actual_user_request_and_accepted_order_catalog_select_without_changing_ledger"],
    "M": ["test_money.MoneyCompatibilityTests.test_request_order_is_preserved_at_a_rounding_boundary",
          "test_m3_completion.ReturnCompletionTests.test_display_estimate_uses_decimal_prices_occurrences_and_half_up"],
    "F": ["test_m3_writes.PreflightTests.test_missing_partial_and_conditional_consent_do_not_read_or_send",
          "test_m3_writes.PreflightTests.test_order_change_after_consent_stops_old_version"],
    "I": ["test_m3_completion.SessionRuntimeTests.test_modify_and_exchange_use_same_product_requested_options_and_exact_diff",
          "test_m5_items.ItemFlowTests.test_natural_recap_last_call_next_consent_single_post_and_owned_readback",
          "test_m5_items.ItemFlowTests.test_additional_item_rebuilds_whole_list_and_does_not_submit_first_line",
          "test_m5_items.ItemFlowTests.test_changed_budget_same_variant_still_requires_new_complete_confirmation",
          "test_m5_items.ItemFlowTests.test_new_competing_candidate_prevents_prior_unique_choice_from_being_sent",
          "test_m5_items.ItemFlowTests.test_repeated_original_units_keep_order_and_full_count_without_quantity_fields",
          "test_m5_items.ItemFlowTests.test_success_locks_second_item_pass_and_other_order_changes",
          "test_m5_items.ItemFlowTests.test_timeout_after_effect_keeps_unknown_and_new_request_cannot_repeat",
          "test_m5_items.ItemEvidenceTests.test_derived_conditions_and_source_indices_are_recomputed_not_trusted_from_metadata",
          "test_m5_items.ItemEvidenceTests.test_all_registered_workflows_are_rejected_by_model_candidate_and_read_binding",
          "test_m5_items.ItemEvidenceTests.test_last_call_mode_and_text_restore_together_and_tampering_is_rejected",
          "test_m5_items.ItemFlowTests.test_zero_quote_accepts_no_row_or_one_upstream_zero_refund_only",
          "test_m5_items.ItemFlowTests.test_zero_quote_extra_nonzero_wrong_destination_or_duplicate_rows_stay_unresolved",
          "test_m5_items.ItemFlowTests.test_compact_eight_item_recap_keeps_every_line_and_sources_without_raw_metadata",
          "test_m5_items.ItemFlowTests.test_recap_over_budget_refuses_whole_list_without_truncation_or_proposal",
          "test_m5_items.ItemEvidenceTests.test_post_send_result_overflow_preserves_unknown_reservation_and_never_retries"],
    "T": ["test_m3_completion.ReturnCompletionTests.test_original_destination_return_recap_confirmation_send_readback_and_restore",
          "test_m3_completion.ReturnCompletionTests.test_late_gift_card_cannot_backfill_opening_eligibility",
          "test_m5_returns.ReturnFlowTests.test_default_prepare_complete_recap_next_consent_one_post_owned_readback",
          "test_m5_returns.ReturnFlowTests.test_estimate_uses_original_price_not_catalog_and_half_up_midpoint",
          "test_m5_returns.ReturnFlowTests.test_identical_duplicate_units_keep_counts_and_original_price_sum",
          "test_m5_returns.ReturnFlowTests.test_mixed_ids_accept_sorted_receipt_and_readback_without_losing_counts",
          "test_m5_returns.ReturnFlowTests.test_missing_or_extra_occurrence_in_receipt_or_readback_cannot_verify",
          "test_m5_returns.ReturnFlowTests.test_unique_legal_current_destination_can_be_recapped_without_extra_choice",
          "test_m5_returns.ReturnFlowTests.test_malformed_saved_methods_preserve_specific_fact_diagnostic",
          "test_m5_returns.ReturnFlowTests.test_many_original_units_exceed_recap_budget_without_partial_proposal_or_send",
          "test_m5_returns.ReturnFlowTests.test_tool_argument_and_result_limits_stop_side_effects_before_send",
          "test_m5_returns.ReturnFlowTests.test_gift_added_after_opening_cannot_backfill_through_new_recap",
          "test_m5_returns.ReturnFlowTests.test_profile_read_before_opening_proves_added_gift_eligibility",
          "test_m5_returns.ReturnFlowTests.test_partial_condition_withdrawal_and_nonadjacent_yes_do_not_submit",
          "test_m5_returns.ReturnFlowTests.test_timeout_after_backend_effect_stays_unknown_and_cannot_repeat",
          "test_m5_returns.ReturnFlowTests.test_lost_execute_bundle_reserves_unknown_without_false_zero_writes",
          "test_m5_returns.ReturnRecoveryTests.test_basis_tampering_of_sources_estimate_or_opening_is_rejected",
          "test_m5_returns.ReturnRecoveryTests.test_shared_business_kinds_restore_and_block_every_peer_without_handoff",
          "test_m5_returns.ReturnRecoveryTests.test_real_schema10_fixture_migrates_without_inventing_return_consent"],
    "X": ["test_m3_completion.SessionRuntimeTests.test_modify_and_exchange_use_same_product_requested_options_and_exact_diff",
          "test_m5_exchanges.ExchangeFlowTests.test_complete_recap_next_consent_one_post_and_owned_readback",
          "test_m5_exchanges.ExchangeFlowTests.test_negative_difference_can_use_other_saved_card_not_return_destination_rules",
          "test_m5_exchanges.ExchangeFlowTests.test_zero_difference_requires_explicit_existing_method_and_keeps_zero",
          "test_m5_exchanges.ExchangeFlowTests.test_positive_gift_must_cover_entire_difference_without_split_or_fallback",
          "test_m5_exchanges.ExchangeFlowTests.test_original_sources_can_swap_variants_without_pending_mutation_ambiguity",
          "test_m5_exchanges.ExchangeFlowTests.test_addition_and_correction_require_new_whole_list_consent",
          "test_m5_exchanges.ExchangeFlowTests.test_new_competitor_invalidates_previous_unique_candidate_before_post",
          "test_m5_exchanges.ExchangeFlowTests.test_after_submission_no_append_method_change_second_exchange_or_return",
          "test_m5_exchanges.ExchangeFlowTests.test_paired_reordering_is_allowed_without_losing_association",
          "test_m5_exchanges.ExchangeFlowTests.test_independent_old_new_sort_cannot_reassign_original_to_wrong_variant",
          "test_m5_exchanges.ExchangeFlowTests.test_shared_store_blocks_stale_snapshot_after_toolkit_reconstruction",
          "test_m5_exchanges.ExchangeFlowTests.test_lost_execute_result_preserves_unknown_reservation_and_no_retry",
          "test_m5_exchanges.ExchangeRecoveryTests.test_basis_source_criteria_price_and_selected_variant_tampering_rejected",
          "test_m5_exchanges.ExchangeRecoveryTests.test_original_schema11_fixture_migrates_without_exchange_consent"],
    "C": ["test_m3_completion.SessionRuntimeTests.test_cancel_with_existing_refund_is_controlled_but_normal_charges_succeed",
          "test_m4_cancellations.CancellationFlowTests.test_full_recap_confirmation_single_post_and_owned_strong_readback",
          "test_m4_cancellations.CancellationFlowTests.test_multi_charge_duplicates_recap_and_refund_independently_without_netting",
          "test_m4_cancellations.CancellationFlowTests.test_existing_refund_is_reviewed_and_not_refunded_again",
          "test_m4_cancellations.CancellationFlowTests.test_successful_payment_switch_then_cancel_reviews_refund_history_without_post",
          "test_m4_cancellations.CancellationFlowTests.test_correcting_malformed_reason_requires_new_recap_before_any_cancellation",
          "test_m4_cancellations.CancellationFlowTests.test_fresh_payment_change_stops_old_version_and_requires_new_confirmation",
          "test_m4_cancellations.CancellationBoundaryTests.test_lost_execute_result_keeps_unknown_and_blocks_other_workflows_and_model"],
    "A": ["test_m4_addresses.AddressFlowTests.test_order_complete_recap_then_verified_update_changes_only_target",
          "test_m4_addresses.AddressFlowTests.test_corrected_unit_rereads_whole_address_and_awaits_new_consent",
          "test_m4_addresses.AddressSafetyTests.test_fresh_backend_change_invalidates_consent_before_any_write",
          "test_m4_address_review.AddressReviewTests.test_failed_preparation_can_retry_recap_and_only_fresh_consent_sends",
          "test_m4_address_review.AddressReviewTests.test_order_success_and_default_unknown_have_separate_results"],
    "D": ["test_m4_addresses.AddressFlowTests.test_default_complete_recap_then_verified_update_leaves_all_orders_unchanged",
          "test_m4_addresses.AddressFlowTests.test_undo_default_requires_fresh_full_recap_and_does_not_undo_order",
          "test_m4_address_review.AddressReviewTests.test_order_success_and_default_rejection_have_separate_results"],
    "P": ["test_m3_completion.SessionRuntimeTests.test_payment_switch_uses_one_original_charge_and_rechecks_full_balance",
          "test_m4_payments.PaymentFlowTests.test_paypal_recap_charge_refund_pending_and_independent_readback",
          "test_m4_payments.PaymentFlowTests.test_insufficient_gift_card_has_zero_writes_and_keeps_original_payment",
          "test_m4_payments.PaymentFlowTests.test_customer_specified_gift_insufficiency_fallback_recap_then_confirmation",
          "test_m4_payments.PaymentFlowTests.test_rejected_charge_keeps_order_and_has_no_refund_or_auto_retry",
          "test_m4_payments.PaymentReviewTests.test_reversed_new_rows_with_matching_readback_verify_records_not_processing_order",
          "test_m4_payments.PaymentReviewTests.test_receipt_order_disagreeing_with_strong_readback_stays_unresolved_without_retry",
          "test_m4_payments.PaymentReviewTests.test_unknown_journal_blocks_a_new_payment_choice_with_specific_code",
          "test_m4_payments.PaymentRecoveryTests.test_shared_claims_stop_stale_payment_snapshot_in_new_toolkit_instance"],
    "H": ["test_m0_contract.ContractBaselineTests.test_transfer_receipt_requires_accepted_and_nonempty_id",
          "test_m4_handoffs.HandoffFlowTests.test_accepted_transfer_uses_exact_201_receipt_and_required_notice",
          "test_m4_handoffs.HandoffFlowTests.test_reducer_accepted_transfer_blocks_future_dispatch_and_model_decisions",
          "test_m4_handoffs.HandoffFlowTests.test_embedded_user_instructions_cannot_replace_summary_facts_or_host_target",
          "test_m4_handoffs.HandoffFlowTests.test_embedded_completion_claim_does_not_promote_unknown_business_result",
          "test_m4_handoffs.HandoffFlowTests.test_unknown_business_operation_is_preserved_in_handoff_summary",
          "test_m4_handoffs.HandoffFlowTests.test_timeout_and_503_stop_business_and_never_retry_transfer",
          "test_m4_handoffs.HandoffRecoveryTests.test_accepted_journal_restore_and_clone_preserve_receipt_sources_and_operations"],
    "L": ["test_m3_writes.PreflightTests.test_default_runtime_cannot_send_a_confirmed_proposal"],
}
# Component relationships, never complete-case executions. These default-turn
# matrix names are checked against actual recorded unittest results.
M55_MATRIX_GROUPS = {
    'I': ['repeated_units_submit_one_complete_payload_and_preserve_counts_across_three_flows',
          'overcount_rejects_whole_list_without_partial_submission_on_all_three_flows',
          'duplicate_id_with_different_original_prices_is_not_silently_assigned_on_any_flow',
          'complete_reduced_list_rebuilds_version_and_only_new_full_consent_can_send',
          'item_modification_lock_blocks_payment_and_cancel_without_new_charge_or_refund',
          'after_success_append_and_method_change_cannot_open_a_second_complete_submission'],
    'T': ['repeated_units_submit_one_complete_payload_and_preserve_counts_across_three_flows',
          'ambiguous_remove_does_not_turn_two_identical_units_into_an_implicit_single_unit_request',
          'mixed_same_order_return_exchange_intent_requires_clarification_before_either_endpoint',
          'return_application_blocks_later_exchange_on_same_order_with_specific_state_code',
          'exchange_application_blocks_later_return_on_same_order_with_specific_state_code',
          'return_gift_destination_is_not_a_positive_difference_charge_and_can_have_zero_balance',
          'return_and_exchange_share_no_implicit_refund_destination_permission'],
    'X': ['repeated_units_submit_one_complete_payload_and_preserve_counts_across_three_flows',
          'mixed_same_order_return_exchange_intent_requires_clarification_before_either_endpoint',
          'exchange_application_blocks_later_return_on_same_order_with_specific_state_code',
          'zero_difference_duplicate_list_with_zero_balance_gift_is_valid_for_modification_and_exchange',
          'zero_difference_still_requires_user_selected_method_before_full_recap',
          'positive_duplicate_difference_requires_gift_to_cover_whole_list_not_one_unit',
          'customer_replaces_insufficient_gift_with_saved_card_then_confirms_new_complete_list',
          'gift_balance_drops_after_full_recap_prevents_old_version_send_for_both_replacement_flows'],
    'C': ['partial_cancellation_english_chinese_and_item_id_scope_never_become_whole_order_proposals',
          'retained_or_excluded_item_scope_cannot_be_promoted_to_whole_cancellation',
          'retained_or_excluded_item_correction_blocks_an_existing_whole_draft',
          'retained_scope_execute_snapshot_rechecks_the_live_user_text_before_any_read',
          'singular_and_plural_item_cancellation_both_mean_narrowed_scope',
          'retention_words_in_reason_data_do_not_reinterpret_whole_order_scope',
          'partial_cancellation_correction_invalidates_whole_order_draft_before_yes',
          'preexisting_partial_scope_execute_snapshot_is_rechecked_without_private_refresh_or_send',
          'explicit_new_whole_order_request_after_partial_denial_requires_fresh_confirmation_and_refunds_full_charge',
          'partial_words_in_reason_and_only_order_scope_do_not_reclassify_an_entire_cancellation',
          'partial_cancellation_intent_from_assistant_or_tool_does_not_change_user_scope',
          'completed_payment_switch_history_cannot_be_netted_into_a_later_cancellation'],
    'W': ['partial_assent_to_a_complete_duplicate_list_does_not_submit_any_flow',
          'current_turn_code_helper_rejects_a_stale_workflow_diagnostic',
          'accepted_unknown_journal_allows_profile_investigation_without_resending_or_resolving_the_write',
          'definite_rejections_preserve_backend_and_do_not_retry_any_product_endpoint',
          'timeout_after_backend_effect_is_unknown_and_blocks_peer_workflow_new_version',
          'unusable_success_receipt_is_unknown_not_completed_and_never_unlocks_another_operation',
          'lost_execute_result_blocks_all_business_peers_and_profile_without_new_reads',
          'shared_claim_store_reconstructed_toolkit_blocks_same_duplicate_list_even_when_backend_looks_unwritten'],
    'H': ['unresolved_product_write_is_preserved_when_handoff_is_accepted'],
}
for group, names in M55_MATRIX_GROUPS.items():
    GROUP_TESTS[group].extend('test_m5_matrix.ProductInteractionMatrixTests.test_' + name for name in names)

GROUP_LIMITATIONS = {
    "G": "Shared identity/ownership prerequisites; not the case dialogue.",
    "W": "Shared consent/single-send lifecycle and finite default workflow matrix; not a complete public business AT.",
    "O": "Owned read boundary; case-specific record discovery still needs a business scenario.",
    "SEL": "M5.1 explicit structured candidate filtering and real-user/accepted-read assessment; not arbitrary shopping language, complete-list proposal/submission or complete public case AT execution.",
    "M": "Action-specific primitive arithmetic only; complete case aggregation belongs to M6.",
    "F": "Structured consent/refresh guards; not all natural-language conditions.",
    "I": "M5.2 finite real-user complete-list producer/last call/next consent/one POST/owned readback on synthetic records; not arbitrary shopping language or complete public business AT execution.",
    "T": "M5.3 finite default return application, original-price estimate, opening-qualified destination and complete consent on synthetic records; not settlement/arrival or full public-case execution.",
    "X": "M5.4 finite default complete delivered exchange, source-derived criteria, signed difference, saved method, one POST and paired receipt/readback on synthetic records; not all language, actual settlement/shipment or full public-case execution.",
    "C": "Finite actual-user cancellation dialogue, per-charge refunds and shared lifecycle; not complete public-case execution or all natural language.",
    "A": "M4.1 actual-user/tool/recap/consent/owned readback on synthetic orders; not the full public case AT dialogue.",
    "D": "M4.1 separate profile address workflow and fresh-confirmation undo; synthetic fixtures, not full public case AT execution.",
    "P": "M4.2 actual-user/saved choice/full-charge recap/consent/readback on synthetic single-original-charge orders; not full public case AT execution or a real payment gateway.",
    "H": "Finite explicit-user default handoff, trusted context, accepted/Unknown and terminal calls; not the complete public dialogue or actual human response.",
    "L": "Default no-write boundary; not every case-specific explanation.",
}


def source_paths(root=ROOT):
    paths = sorted(list((root / "agent").rglob("*.py")) + list((root / "tests").rglob("*.py")) +
                   list((root / "tests" / "fixtures").glob("*.json")) +
                   [root / "agent" / "agent.json", root / "scripts" / "foundation_trace.py",
                    root / "scripts" / "local_dialogue_batch.py", root / "scripts" / "evidence_docs.py",
                    root / "scripts" / "local_replay_batch.py", root / "scripts" / "local_boundary_batch.py"])
    return [path for path in paths if "__pycache__" not in path.parts]


def source_file_hashes(root=ROOT):
    """Reviewable file bytes; no Git, credentials or unselected docs required."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_paths(root)}


def source_digest(root=ROOT):
    digest = hashlib.sha256()
    for path in source_paths(root):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def specification_snapshot(root=ROOT):
    """Explicit public spec allowlist; not every doc, raw material or credential."""
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
             for name in SPECIFICATION_PATHS}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"specification_sha256": digest, "specification_files": files}


def input_snapshot(root=ROOT):
    requirements = (root / "docs" / "CASE-REQUIREMENTS.md").read_text(encoding="utf-8")
    return {"source_sha256": source_digest(root),
            "source_files": source_file_hashes(root),
            "requirements_sha256": hashlib.sha256(requirements.encode()).hexdigest(),
            **specification_snapshot(root)}


def build_trace(requirements, report, *, expected_source_digest, expected_specification_digest, groups=None, allow_oracle_control=False):
    groups = GROUP_TESTS if groups is None else groups
    if (not isinstance(report.get("run_id"), str) or not report["run_id"]
            or report.get("status") != "passed" or report.get("source_sha256") != expected_source_digest
            or report.get("specification_sha256") != expected_specification_digest
            or report.get("requirements_sha256") != hashlib.sha256(requirements.encode()).hexdigest()
            or report.get("exit_code") != 0 or report.get("skipped") != 0
            or report.get("failures") != 0 or report.get("errors") != 0
            or not isinstance(report.get("results"), dict)):
        raise ValueError("Trace requires a successful, unskipped run of the exact source workspace")
    files = report.get('source_files')
    if not isinstance(files, dict) or not files or any(
            not isinstance(name, str) or not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
            for name, value in files.items()):
        raise ValueError('Trace requires per-file source hashes')
    for ids in groups.values():
        if not ids or any(report["results"].get(test_id) != "passed" for test_id in ids):
            raise ValueError("A referenced component test was not executed successfully")
    records = []
    pattern = re.compile(r"^- A(\d{3})-(\d{2}) \[[^;]+; ([A-Z]+(?:,[A-Z]+)*)\] .+$")
    for number, line in enumerate(requirements.splitlines(), 1):
        if not line.startswith("- A"):
            continue
        match = pattern.fullmatch(line)
        if match is None:
            raise ValueError("An atomic requirement has an unsupported shape")
        case, atomic, codes = match.groups()
        codes = codes.split(",")
        if any(c not in groups for c in codes):
            raise ValueError("Unknown requirement group")
        components = ["G"] + (["W"] if set(codes) & {"I", "T", "X", "C", "A", "D", "P"} else []) + codes
        records.append({"at_id": f"AT-A{case}-{atomic}", "case_id": int(case),
                        "requirement_line": number, "component_groups": list(dict.fromkeys(components)),
                        "component_result": "related_components_passed",
                        "business_result": "not_executed", "business_test_ids": [], "remote_result": "not_run"})
    if (len(records) != 522 or len({r["at_id"] for r in records}) != 522
            or {r["case_id"] for r in records} != set(range(134))):
        raise ValueError("Expected the unchanged 134-case / 522-AT inventory")
    result = {"schema_version": 2, "status": "valid", "run_id": report["run_id"],
            "scope": "component association, not complete business-AT execution",
            "case_count": 134, "at_count": 522, "business_ats_executed": 0,
            "requirements_sha256": hashlib.sha256(requirements.encode()).hexdigest(),
            "run_source_sha256": expected_source_digest,
            "source_files": files,
            "specification_sha256": expected_specification_digest,
            "specification_files": report["specification_files"],
            "groups": {code: {"test_ids": ids, "limitation": GROUP_LIMITATIONS.get(code, "Related component only.")}
                       for code, ids in groups.items()}, "records": records}
    dialogues = trace_dialogues(requirements, report, allow_oracle_control=allow_oracle_control)
    if dialogues is not None:
        result['local_dialogues'] = dialogues
        links = {r['at_id']:r['dialogue_ids'] for r in dialogues['plan']}
        for record in result['records']:
            record['local_dialogue_ids'] = links[record['at_id']]
            record['local_dialogue_result'] = ('related_synthetic_dialogues_passed'
                                              if links[record['at_id']] else 'not_scheduled')
    replays = _replay_module.trace_replays(report, _dialogue_module.load_manifest(), allow_oracle_control=allow_oracle_control)
    if replays is not None:
        result['local_replays'] = replays
    boundaries = _boundary_module.trace_boundaries(report)
    if boundaries is not None:
        result['local_boundaries'] = boundaries
    return result


def validate_evidence_pair(requirements, report, trace, *, snapshot, allow_oracle_control=False):
    """Consumers must validate both artifacts, not a source hash alone."""
    expected = build_trace(requirements, report, expected_source_digest=snapshot["source_sha256"],
                           expected_specification_digest=snapshot["specification_sha256"], allow_oracle_control=allow_oracle_control)
    if (trace != expected or report["specification_files"] != snapshot["specification_files"]
            or report['source_files'] != snapshot['source_files']):
        raise ValueError("Evidence is stale, invalid, or from a different run")


def _write_json_atomic(path, value):
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False, allow_nan=False)
            output.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _invalidate_trace(path, run_id, reason):
    _write_json_atomic(path, {"schema_version": 2, "status": "invalid", "run_id": run_id,
                             "reason": reason, "scope": "no current component pass evidence"})


def publish_run(requirements, report, *, snapshot, report_path, trace_path):
    """Fail closed between file replacements; no two-file transaction is assumed."""
    if report_path.resolve() == trace_path.resolve():
        raise ValueError("Report and trace must be distinct files")
    _invalidate_trace(trace_path, report["run_id"], "publication_in_progress")
    report = dict(report)
    current_trace = None
    if report["status"] == "passed":
        try:
            if report.get('source_files') != snapshot['source_files']:
                raise ValueError('Per-file source hashes differ from current inputs')
            current_trace = build_trace(requirements, report,
                    expected_source_digest=snapshot["source_sha256"],
                    expected_specification_digest=snapshot["specification_sha256"])
        except ValueError as error:
            report.update(status="trace_rejected", exit_code=1, evidence_error=str(error))
    if current_trace is None:
        report["exit_code"] = 1
    _write_json_atomic(report_path, report)
    if current_trace is None:
        _invalidate_trace(trace_path, report["run_id"], report["status"])
        return 1
    _write_json_atomic(trace_path, current_trace)
    return 0


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test); self.outcomes.setdefault(test.id(), "passed")

    def addFailure(self, test, error):
        super().addFailure(test, error); self.outcomes[test.id()] = "failed"

    def addError(self, test, error):
        super().addError(test, error); self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.outcomes[test.id()] = "skipped"

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None: self.outcomes[test.id()] = "failed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "FOUNDATION-RUN.json")
    parser.add_argument("--trace", type=Path, default=ROOT / "docs" / "AT-TEST-TRACE.json")
    args = parser.parse_args(argv)
    if args.report.resolve() == args.trace.resolve():
        parser.error("Report and trace must be distinct files")
    run_id = uuid4().hex
    _invalidate_trace(args.trace, run_id, "run_in_progress")
    sys.path.insert(0, str(ROOT / "tests"))
    before = input_snapshot()
    _write_json_atomic(args.report, {"schema_version": 2, "run_id": run_id, "status": "running",
                                    "exit_code": 1, **before})
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    started = time.monotonic()
    native_modules = {key:sys.modules.get(name) for key,name in
                      (('dialogue_batch','test_m6_dialogues'), ('replay_batch','test_m6_replays'),
                       ('boundary_batch','test_m6_boundaries'))}
    saved = {key:(getattr(module,'PARENT_RUN',None),getattr(module,'BATCH_EVIDENCE',None))
             for key,module in native_modules.items() if module is not None}
    native_evidence = {}
    for module in native_modules.values():
        if module is not None:
            module.PARENT_RUN = {'run_id':run_id, 'source_sha256':before['source_sha256']}
            module.BATCH_EVIDENCE = None
    try:
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        native_evidence = {key:getattr(module,'BATCH_EVIDENCE',None) for key,module in native_modules.items()}
    finally:
        for key,module in native_modules.items():
            if module is not None:
                module.PARENT_RUN, module.BATCH_EVIDENCE = saved[key]
    after = input_snapshot()
    success = (result.wasSuccessful() and not result.skipped and before == after
               and len(result.outcomes) == result.testsRun)
    status = "passed" if success else ("inputs_changed" if before != after else "tests_not_passed")
    report = {"schema_version": 2, "run_id": run_id, "status": status,
              "scope": "offline workspace; fake API/gateway; SDK subprocesses included, not added",
              **before, "tests_run": result.testsRun, "skipped": len(result.skipped),
              "failures": len(result.failures), "errors": len(result.errors), "elapsed_seconds": round(time.monotonic()-started, 3),
              "exit_code": 0 if success else 1, "results": dict(sorted(result.outcomes.items()))}
    for key, value in native_evidence.items():
        if value is not None:
            report[key] = value
    exit_code = publish_run((ROOT / "docs" / "CASE-REQUIREMENTS.md").read_text(encoding="utf-8"), report,
                           snapshot=after, report_path=args.report, trace_path=args.trace)
    if exit_code: return exit_code
    print(f"FOUNDATION_RUN_PASSED {result.testsRun}; 134 cases / 522 AT records; full business ATs executed 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
