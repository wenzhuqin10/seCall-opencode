import json
import tempfile
import unittest
from pathlib import Path

from secall_opencode.chatgpt import inspect_export, parse_export
from secall_opencode.config import Config
from secall_opencode.server import import_chatgpt, list_vault_sessions


FIXTURE = Path(__file__).parent / "fixtures" / "chatgpt_conversations.json"


class ChatGPTImportTests(unittest.TestCase):
    def test_active_branch_is_recovered(self):
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        conversations = parse_export(value)
        self.assertEqual(len(conversations), 1)
        self.assertEqual(len(conversations[0].messages), 3)
        rendered = json.dumps(conversations[0].messages, ensure_ascii=False)
        self.assertIn("src/mac/scheduler.c", rendered)
        self.assertNotIn("这条分支不应导入", rendered)

    def test_inspect_and_import(self):
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        summary = inspect_export(value)
        self.assertEqual(summary["conversation_count"], 1)
        self.assertEqual(summary["message_count"], 3)

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(vault=Path(tmp))
            result = import_chatgpt(config, value, "wireless-baseband")
            sessions = list_vault_sessions(config)
            self.assertEqual(result["imported"], 1)
            self.assertEqual(sessions[0]["source"], "chatgpt")
            content = Path(sessions[0]["path"]).read_text(encoding="utf-8")
            self.assertIn('source: "chatgpt"', content)
            self.assertIn("HARQ timeout", content)


if __name__ == "__main__":
    unittest.main()
