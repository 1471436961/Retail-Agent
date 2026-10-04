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
          "test_m3_completion.SessionRuntimeTests.test_stale_snapshot_extra_history_and_new_runtime_share_stable_claim"],
    "O": ["test_m2_reads.ReadEndpointTests.test_owned_reference_with_wrong_returned_owner_or_id_is_rejected"],
    "SEL": ["test_m3_completion.SessionRuntimeTests.test_wrong_requested_options_block_before_claim_or_http_write"],
    "M": ["test_money.MoneyCompatibilityTests.test_request_order_is_preserved_at_a_rounding_boundary",
          "test_m3_completion.ReturnCompletionTests.test_display_estimate_uses_decimal_prices_occurrences_and_half_up"],
    "F": ["test_m3_writes.PreflightTests.test_missing_partial_and_conditional_consent_do_not_read_or_send",
          "test_m3_writes.PreflightTests.test_order_change_after_consent_stops_old_version"],
    "I": ["test_m3_completion.SessionRuntimeTests.test_modify_and_exchange_use_same_product_requested_options_and_exact_diff"],
    "T": ["test_m3_completion.ReturnCompletionTests.test_original_destination_return_recap_confirmation_send_readback_and_restore",
          "test_m3_completion.ReturnCompletionTests.test_late_gift_card_cannot_backfill_opening_eligibility"],
    "X": ["test_m3_completion.SessionRuntimeTests.test_modify_and_exchange_use_same_product_requested_options_and_exact_diff"],
    "C": ["test_m3_completion.SessionRuntimeTests.test_cancel_with_existing_refund_is_controlled_but_normal_charges_succeed"],
    "A": ["test_m4_addresses.AddressFlowTests.test_order_complete_recap_then_verified_update_changes_only_target",
          "test_m4_addresses.AddressFlowTests.test_corrected_unit_rereads_whole_address_and_awaits_new_consent",
          "test_m4_addresses.AddressSafetyTests.test_fresh_backend_change_invalidates_consent_before_any_write",
          "test_m4_address_review.AddressReviewTests.test_failed_preparation_can_retry_recap_and_only_fresh_consent_sends",
          "test_m4_address_review.AddressReviewTests.test_order_success_and_default_unknown_have_separate_results"],
    "D": ["test_m4_addresses.AddressFlowTests.test_default_complete_recap_then_verified_update_leaves_all_orders_unchanged",
          "test_m4_addresses.AddressFlowTests.test_undo_default_requires_fresh_full_recap_and_does_not_undo_order",
          "test_m4_address_review.AddressReviewTests.test_order_success_and_default_rejection_have_separate_results"],
    "P": ["test_m3_completion.SessionRuntimeTests.test_payment_switch_uses_one_original_charge_and_rechecks_full_balance"],
    "H": ["test_m0_contract.ContractBaselineTests.test_transfer_receipt_requires_accepted_and_nonempty_id"],
    "L": ["test_m3_writes.PreflightTests.test_default_runtime_cannot_send_a_confirmed_proposal"],
}
GROUP_LIMITATIONS = {
    "G": "Shared identity/ownership prerequisites; not the case dialogue.",
    "W": "Shared consent/single-send lifecycle; not a business producer.",
    "O": "Owned read boundary; case-specific record discovery still needs a business scenario.",
    "SEL": "Selected-option validation only; preference, ranking and fallback producer belongs to M5.",
    "M": "Action-specific primitive arithmetic only; complete case aggregation belongs to M6.",
    "F": "Structured consent/refresh guards; not all natural-language conditions.",
    "I": "Explicit structured adapter; M5 complete-list producer not implemented.",
    "T": "Explicit original-price estimate/destination adapter; M5 dialogue not implemented.",
    "X": "Explicit variant adapter; M5 candidate dialogue not implemented.",
    "C": "Explicit cancellation adapter and exception policy; M4 dialogue not implemented.",
    "A": "M4.1 actual-user/tool/recap/consent/owned readback on synthetic orders; not the full public case AT dialogue.",
    "D": "M4.1 separate profile address workflow and fresh-confirmation undo; synthetic fixtures, not full public case AT execution.",
    "P": "Supported single-charge adapter; M4 payment dialogue not included in this address release.",
    "H": "Schema-only transfer receipt check; production handoff belongs to M4.",
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
