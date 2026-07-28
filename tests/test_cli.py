import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "opencode_session.json"


class CliTests(unittest.TestCase):
    def test_convert_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            src = str(Path(__file__).parents[1] / "src")
            env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "secall_opencode",
                    "--json",
                    "--vault",
                    tmp,
                    "convert",
                    str(FIXTURE),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=env,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["result"]["session_id"], "ses_test_001")


if __name__ == "__main__":
    unittest.main()
