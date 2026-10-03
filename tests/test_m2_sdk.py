"""Run genuine tau2 checks in a clean subprocess, unaffected by M1 sys.modules fakes."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


class GenuineSDKTests(unittest.TestCase):
    def test_missing_sdk_interpreter_is_failure_not_skip(self):
        with patch.object(Path, "is_file", return_value=False):
            with self.assertRaises(AssertionError):
                self.test_real_sdk_read_tools_and_gateway_round_trip_offline()

    def test_real_sdk_read_tools_and_gateway_round_trip_offline(self):
        root = Path(__file__).resolve().parents[1]
        interpreter = root / ".venv" / "Scripts" / "python.exe"
        self.assertTrue(interpreter.is_file(), "M2 acceptance requires the project tau2 venv; SDK evidence must not be skipped")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(PYTHON_DOTENV_DISABLED="1", HF_HUB_OFFLINE="1", LITELLM_TELEMETRY="False", LITELLM_LOCAL_MODEL_COST_MAP="True")
        result = subprocess.run([str(interpreter), str(root / "tests" / "sdk_m2_checks.py")],
                                cwd=root, env=env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"REAL_SDK_CHECKS_PASSED [1-9][0-9]*; skipped 0; model gateway was fake; network attempts 0")
