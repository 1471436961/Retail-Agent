"""Exercise indexing with synthetic case text, without external materials."""

import runpy
import unittest
from pathlib import Path

from temp_dirs import temporary_directory


ROOT = Path(__file__).resolve().parents[1]
TRACE = runpy.run_path(str(ROOT / "scripts/build-case-trace.py"), run_name="trace_tests")
COVERAGE = ROOT / "docs/CASE-COVERAGE.md"


class CaseTraceTests(unittest.TestCase):
    def synthetic_cases(self):
        groups = TRACE["coverage_groups"](COVERAGE)
        lines = ["# Synthetic public requirements"]
        for case_id in range(134):
            lines.extend([f"## Synthetic ID {case_id}", "### Need", "Synthetic customer request.", "### Expected"])
            lines.extend("- Synthetic expected behavior" for _ in groups[case_id])
            lines.append("### Business")
            lines.extend("- Synthetic business requirement" for _ in range(2 if case_id < 34 else 1))
        return "\n".join(lines) + "\n"

    def test_reordering_categories_does_not_change_generated_trace(self):
        with temporary_directory() as folder:
            cases, changed = Path(folder) / "cases.md", Path(folder) / "coverage.md"
            cases.write_text(self.synthetic_cases(), encoding="utf-8")
            original = TRACE["build"](cases, COVERAGE)
            lines = COVERAGE.read_text(encoding="utf-8").splitlines()
            indices = [i for i, line in enumerate(lines) if line.startswith("| ") and len(line.split("|")) == 5 and line.split("|")[2].strip().isdigit()]
            rows = [lines[i] for i in indices]
            for index, row in zip(indices, reversed(rows)):
                lines[index] = row
            changed.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(TRACE["build"](cases, changed), original)
            self.assertEqual(TRACE["coverage_groups"](changed)[0], ["EXCHANGE"])
            self.assertEqual(TRACE["coverage_groups"](changed)[33], ["DEFAULT_ADDR"])

    def test_unknown_and_duplicate_category_names_fail_closed(self):
        text = COVERAGE.read_text(encoding="utf-8")
        with temporary_directory() as folder:
            changed = Path(folder) / "coverage.md"
            for replacement in ("Unknown category", "已送达商品退货"):
                with self.subTest(replacement=replacement):
                    changed.write_text(text.replace("| 待处理订单商品修改 |", f"| {replacement} |", 1), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Unknown or duplicate"):
                        TRACE["coverage_groups"](changed)

    def test_business_requirement_count_is_pinned_to_materials_version(self):
        with temporary_directory() as folder:
            cases = Path(folder) / "cases.md"
            cases.write_text(self.synthetic_cases().replace("- Synthetic business requirement\n", "", 1), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Coverage totals changed"):
                TRACE["build"](cases, COVERAGE)


if __name__ == "__main__":
    unittest.main()
