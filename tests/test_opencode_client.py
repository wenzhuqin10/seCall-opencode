import unittest

from secall_opencode.opencode_client import extract_generation_text


class OpenCodeClientTests(unittest.TestCase):
    def test_extract_json_event_text(self):
        raw = "\n".join(
            [
                '{"type":"step_start"}',
                '{"type":"text","part":{"text":"第一段"}}',
                '{"type":"text","part":{"text":"第二段"}}'
            ]
        )
        self.assertEqual(extract_generation_text(raw), "第一段\n第二段")

    def test_extract_plain_text(self):
        self.assertEqual(extract_generation_text("直接输出"), "直接输出")


if __name__ == "__main__":
    unittest.main()
