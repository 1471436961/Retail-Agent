"""Rule checks plus a fresh-process production SDK/semantic integration worker."""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from sdk_m7_semantic_checks import SemanticCandidateTests

ROOT = Path(__file__).resolve().parents[1]


class NativeSemanticWorkerTests(unittest.TestCase):
    def test_production_factory_sdk_return_and_semantic_authorization(self):
        python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.assertTrue(python.is_file(), 'Installed SDK interpreter is required, not skipped')
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env.update(PYTHON_DOTENV_DISABLED='1', LITELLM_LOCAL_MODEL_COST_MAP='True')
        result = subprocess.run([str(python), '-B', str(ROOT / 'tests/sdk_m7_semantic_checks.py'),
                                 'NativeSemanticTests', '-v'], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=240)
        self.assertEqual(result.returncode, 0, result.stdout[-1000:] + result.stderr[-16000:])
        self.assertRegex(result.stderr, r'(?m)^Ran \d+ tests? in ')
        self.assertEqual(int(re.search(r'(?m)^Ran (\d+) tests? in ', result.stderr).group(1)), 23,
                         'The fixed native integration inventory must not silently lose cases')
        self.assertRegex(result.stderr, r'(?m)^OK\s*$')
        self.assertNotIn('OK (skipped=', result.stderr)
        self.assertIn('network_attempts:0 real_model_calls:0', result.stdout)


if __name__ == '__main__':
    unittest.main()
