"""Offline regression tests for the Jev integration. No network/API key required."""
import json
import tempfile
import unittest
from pathlib import Path

from jev_client import answer_choice, answer_confidence, answer_noul, choice_probability, config_summary
from jev_decide import (
    _labels_from_file,
    formal_metric_labels,
    judge_band_records,
    route_evidence_records,
    screen_search_records,
    verify_claim_records,
)


class FakeClient:
    def system_one(self, state, questions, model=None):
        answers = {}
        for key, q in questions.items():
            if q.get("type") == "choice":
                choices = list(q["criteria"])
                choice = choices[0]
                answers[key] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.91,
                    "probabilities": {choice: 0.91},
                }
            elif key.startswith("entity_") or key == "target_entity":
                answers[key] = {"type": "noul", "noul": 0.95}
            elif key.startswith("open_"):
                answers[key] = {"type": "noul", "noul": 0.90}
            elif key.startswith("primary_"):
                answers[key] = {"type": "noul", "noul": 0.80}
            elif key == "label_0":
                answers[key] = {"type": "noul", "noul": 0.92}
            elif key.startswith("label_"):
                answers[key] = {"type": "noul", "noul": 0.10}
            elif key == "supports":
                answers[key] = {"type": "noul", "noul": 0.93}
            elif key == "contradicts":
                answers[key] = {"type": "noul", "noul": 0.02}
            else:
                answers[key] = {"type": "noul", "noul": 0.5}
        return {"model": "fake", "answers": answers, "usage": {"input_tokens": 123}}


class JevIntegrationTests(unittest.TestCase):
    def test_answer_helpers(self):
        self.assertEqual(answer_noul({"noul": 0.7}), 0.7)
        ans = {"choice": "A", "confidence": 0.8, "probabilities": {"A": 0.83}}
        self.assertEqual(answer_choice(ans), "A")
        self.assertEqual(answer_confidence(ans), 0.8)
        self.assertEqual(choice_probability(ans), 0.83)

    def test_formal_labels_are_23_metrics(self):
        labels = formal_metric_labels()
        self.assertEqual(len(labels), 23)
        self.assertEqual(len({x["id"] for x in labels}), 23)

    def test_custom_45_faces_supported(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "labels.json"
            p.write_text(json.dumps({"labels": [
                {"id": f"face_{i:02d}", "description": f"面{i}"} for i in range(1, 46)
            ]}, ensure_ascii=False), encoding="utf-8")
            labels = _labels_from_file(str(p))
            self.assertEqual(len(labels), 45)

    def test_screen_search(self):
        rows = [{"id": "r1", "title": "新工厂", "snippet": "公司建设新生产基地", "url": "https://example.com/a"}]
        result = screen_search_records(FakeClient(), rows, company="示例企业")
        self.assertEqual(result["summary"]["kept"], 1)
        self.assertTrue(result["records"][0]["jev"]["keep"])
        self.assertGreater(result["records"][0]["jev"]["priority"], 0.7)

    def test_route_evidence_multilabel(self):
        rows = [{"id": "p1", "text": "公司新建工厂", "url": "https://example.com/a"}]
        labels = [{"id": "capacity", "description": "产能扩张"}, {"id": "ma", "description": "并购"}]
        result = route_evidence_records(FakeClient(), rows, labels, "示例企业", 0.7, 2)
        self.assertEqual(result["records"][0]["jev"]["matches"], ["capacity"])
        self.assertEqual(result["records"][0]["jev"]["target_entity_probability"], 0.95)

    def test_judge_band_is_advisory(self):
        rows = [{"id": "b1", "company_name": "示例企业", "evidence": "证据文本"}]
        result = judge_band_records(FakeClient(), rows, "capacity", 1)
        j = result["records"][0]["jev"]
        self.assertTrue(j["advisory_only"])
        self.assertIsInstance(j["band_choice"], str)
        self.assertGreater(j["band_probability"], 0.8)

    def test_verify_claims(self):
        rows = [{"id": "v1", "claim": "公司建设新工厂", "evidence": "公司公告称建设新工厂"}]
        result = verify_claim_records(FakeClient(), rows, 1)
        j = result["records"][0]["jev"]
        self.assertEqual(j["support_probability"], 0.93)
        self.assertEqual(j["contradiction_probability"], 0.02)

    def test_config_does_not_expose_key(self):
        data = config_summary()
        self.assertNotIn("api_key", data)


if __name__ == "__main__":
    unittest.main()
