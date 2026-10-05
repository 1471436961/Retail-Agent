"""Actual unittest evidence and complete AT inventory, never a business score.

Run: project-python -B scripts/foundation_trace.py
The generated reports are local offline evidence. A related component test
passing does not execute a complete public business AT or a remote evaluation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
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
    "X": ["test_m3_completion.SessionRuntimeTests.test_modify_and_exchange_use_same_product_requested_options_and_exact_diff"],
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
GROUP_LIMITATIONS = {
    "G": "Shared identity/ownership prerequisites; not the case dialogue.",
    "W": "Shared consent/single-send lifecycle and finite default workflow matrix; not a complete public business AT.",
    "O": "Owned read boundary; case-specific record discovery still needs a business scenario.",
    "SEL": "M5.1 explicit structured candidate filtering and real-user/accepted-read assessment; not arbitrary shopping language, complete-list proposal/submission or complete public case AT execution.",
    "M": "Action-specific primitive arithmetic only; complete case aggregation belongs to M6.",
    "F": "Structured consent/refresh guards; not all natural-language conditions.",
    "I": "M5.2 finite real-user complete-list producer/last call/next consent/one POST/owned readback on synthetic records; not arbitrary shopping language or complete public business AT execution.",
    "T": "Explicit original-price estimate/destination adapter; M5 dialogue not implemented.",
    "X": "Explicit variant adapter; M5 candidate dialogue not implemented.",
    "C": "Finite actual-user cancellation dialogue, per-charge refunds and shared lifecycle; not complete public-case execution or all natural language.",
    "A": "M4.1 actual-user/tool/recap/consent/owned readback on synthetic orders; not the full public case AT dialogue.",
    "D": "M4.1 separate profile address workflow and fresh-confirmation undo; synthetic fixtures, not full public case AT execution.",
    "P": "M4.2 actual-user/saved choice/full-charge recap/consent/readback on synthetic single-original-charge orders; not full public case AT execution or a real payment gateway.",
    "H": "Finite explicit-user default handoff, trusted context, accepted/Unknown and terminal calls; not the complete public dialogue or actual human response.",
    "L": "Default no-write boundary; not every case-specific explanation.",
}


def source_digest(root=ROOT):
    paths = sorted(list((root / "agent").rglob("*.py")) + list((root / "tests").rglob("*.py")) +
                   list((root / "tests" / "fixtures").glob("*.json")) +
                   [root / "agent" / "agent.json", root / "scripts" / "foundation_trace.py"])
    digest = hashlib.sha256()
    for path in paths:
        if "__pycache__" not in path.parts:
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
            "requirements_sha256": hashlib.sha256(requirements.encode()).hexdigest(),
            **specification_snapshot(root)}


def build_trace(requirements, report, *, expected_source_digest, expected_specification_digest, groups=None):
    groups = GROUP_TESTS if groups is None else groups
    if (not isinstance(report.get("run_id"), str) or not report["run_id"]
            or report.get("status") != "passed" or report.get("source_sha256") != expected_source_digest
            or report.get("specification_sha256") != expected_specification_digest
            or report.get("requirements_sha256") != hashlib.sha256(requirements.encode()).hexdigest()
            or report.get("exit_code") != 0 or report.get("skipped") != 0
            or report.get("failures") != 0 or report.get("errors") != 0
            or not isinstance(report.get("results"), dict)):
        raise ValueError("Trace requires a successful, unskipped run of the exact source workspace")
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
    return {"schema_version": 2, "status": "valid", "run_id": report["run_id"],
            "scope": "component association, not complete business-AT execution",
            "case_count": 134, "at_count": 522, "business_ats_executed": 0,
            "requirements_sha256": hashlib.sha256(requirements.encode()).hexdigest(),
            "run_source_sha256": expected_source_digest,
            "specification_sha256": expected_specification_digest,
            "specification_files": report["specification_files"],
            "groups": {code: {"test_ids": ids, "limitation": GROUP_LIMITATIONS.get(code, "Related component only.")}
                       for code, ids in groups.items()}, "records": records}


def validate_evidence_pair(requirements, report, trace, *, snapshot):
    """Consumers must validate both artifacts, not a source hash alone."""
    expected = build_trace(requirements, report, expected_source_digest=snapshot["source_sha256"],
                           expected_specification_digest=snapshot["specification_sha256"])
    if trace != expected or report["specification_files"] != snapshot["specification_files"]:
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
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    after = input_snapshot()
    success = (result.wasSuccessful() and not result.skipped and before == after
               and len(result.outcomes) == result.testsRun)
    status = "passed" if success else ("inputs_changed" if before != after else "tests_not_passed")
    report = {"schema_version": 2, "run_id": run_id, "status": status,
              "scope": "offline workspace; fake API/gateway; SDK subprocesses included, not added",
              **before, "tests_run": result.testsRun, "skipped": len(result.skipped),
              "failures": len(result.failures), "errors": len(result.errors), "elapsed_seconds": round(time.monotonic()-started, 3),
              "exit_code": 0 if success else 1, "results": dict(sorted(result.outcomes.items()))}
    exit_code = publish_run((ROOT / "docs" / "CASE-REQUIREMENTS.md").read_text(encoding="utf-8"), report,
                           snapshot=after, report_path=args.report, trace_path=args.trace)
    if exit_code: return exit_code
    print(f"FOUNDATION_RUN_PASSED {result.testsRun}; 134 cases / 522 AT records; full business ATs executed 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
