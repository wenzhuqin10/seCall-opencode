import tempfile
import unittest
import json
from pathlib import Path

from secall_opencode.knowledge import split_document_and_qa, store_knowledge


OUTPUT = """<!-- ISSUE_CARD_START -->
# HARQ timeout

## 根因分析
状态未清零。
<!-- ISSUE_CARD_END -->
<!-- QA_JSON_START -->
[
  {
    "question": "HARQ timeout 应首先检查什么？",
    "answer": "检查 HARQ 状态是否清零。",
    "qa_type": "troubleshooting",
    "evidence": ["Session 中的 grep 结果"]
  }
]
<!-- QA_JSON_END -->"""


class KnowledgeTests(unittest.TestCase):
    def test_parse_and_deduplicate(self):
        document, qa = split_document_and_qa(OUTPUT)
        self.assertEqual(len(qa), 1)

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            source = "---\nsession_id: ses_test_001\nproject: demo\n---\n"
            first = store_knowledge(
                OUTPUT, source, vault, "wiki/issues", "knowledge/qa/candidates.jsonl"
            )
            second = store_knowledge(
                OUTPUT, source, vault, "wiki/issues", "knowledge/qa/candidates.jsonl"
            )
            self.assertEqual(first.qa_count, 1)
            self.assertEqual(second.qa_count, 0)
            self.assertTrue(first.issue_path.exists())
            qa_record = json.loads(
                first.qa_path.read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(qa_record["knowledge_id"], first.issue_path.stem)

    def test_rejects_unmarked_output(self):
        document, qa = split_document_and_qa("# ordinary markdown")
        self.assertEqual(document, "# ordinary markdown\n")
        self.assertEqual(qa, [])


if __name__ == "__main__":
    unittest.main()
