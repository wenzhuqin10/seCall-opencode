import json
import tempfile
import unittest
from pathlib import Path

from secall_opencode.converter import convert_export, validate_export


FIXTURE = Path(__file__).parent / "fixtures" / "opencode_session.json"


class ConverterTests(unittest.TestCase):
    def test_convert_preserves_evidence_and_is_idempotent(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            first = convert_export(data, Path(tmp))
            second = convert_export(data, Path(tmp))
            content = first.output_path.read_text(encoding="utf-8")

            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertIn("source: opencode", content)
            self.assertIn('model: "glm-5.1"', content)
            self.assertIn("ses_test_001", content)
            self.assertIn("HARQ timeout", content)
            self.assertIn("src/mac/scheduler.c:320", content)

    def test_rejects_invalid_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                validate_export({"messages": []})


if __name__ == "__main__":
    unittest.main()
