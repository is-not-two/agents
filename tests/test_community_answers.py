"""Community evidence selection contract; no provider or database traffic."""
import json
import sys
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rag_tech_retriever.platform.community_answers import CommunityAnswers

MODULE="rag_tech_retriever.platform.community_answers.post_chat"

def row(i, body):
    return {"id":str(i),"title":"source "+str(i),"version":1,"body":body}

class EvidenceContract(unittest.TestCase):
    def setUp(self):
        self.engine=CommunityAnswers(lambda:{"model":"test"},1,1)

    def test_long_first_source_cannot_hide_later_answer(self):
        target="会议纪要应核对负责人和截止时间。"
        def choose(config,payload,*args):
            data=json.loads(payload["messages"][1]["content"])
            ids=[i for i,text in data["sources"] if text==target]
            self.assertTrue(ids)
            self.assertLessEqual(len(data["sources"]),40)
            return {"choices":[{"message":{"content":json.dumps(ids)}}]}
        with patch(MODULE,side_effect=choose):
            result=self.engine.answer("如何核对？",[row(1,"无关内容。"*200),row(2,target)])
        self.assertEqual(result["mode"],"ai_evidence")
        self.assertEqual(result["evidence"][0]["post_id"],"2")
        self.assertEqual(result["evidence"][0]["quote"],target)

    def test_busy_fallback_covers_distinct_sources_without_call(self):
        self.engine.slots.acquire()
        try:
            with patch(MODULE) as provider:
                result=self.engine.answer("?",[row(i,"片段。"*100) for i in range(8)])
                provider.assert_not_called()
            self.assertEqual([x["post_id"] for x in result["evidence"]],["0","1","2"])
        finally:self.engine.slots.release()

    def test_invalid_or_boolean_selection_is_not_accepted_as_evidence(self):
        for invalid in ("[true]","[99]",'{"quote":"forged"}'):
            with self.subTest(invalid=invalid),patch(MODULE,return_value={"choices":[{"message":{"content":invalid}}]}):
                result=self.engine.answer("?",[row(1,"原句。")])
                self.assertEqual(result["mode"],"keyword")
                self.assertEqual(result["evidence"][0]["quote"],"原句。")

    def test_duplicate_indices_deduplicated(self):
        with patch(MODULE,return_value={"choices":[{"message":{"content":"[0,0]"}}]}):
            result=self.engine.answer("?",[row(1,"原句。")])
        self.assertEqual(len(result["evidence"]),1)

    def test_empty_sources_do_not_call_model(self):
        with patch(MODULE) as provider:
            self.assertEqual(self.engine.answer("?",[])["mode"],"no_evidence")
            provider.assert_not_called()

    def test_empty_selection_abstains(self):
        with patch(MODULE,return_value={"choices":[{"message":{"content":"[]"}}]}):
            self.assertEqual(self.engine.answer("?",[row(1,"原句。")])["mode"],"no_evidence")

class DeadlineContract(unittest.TestCase):
    def test_total_deadline_retains_busy_slot_until_transport_finishes(self):
        engine=CommunityAnswers(lambda:{"model":"test"},1,.05)
        release=Event();started=Event()
        def slow(*args):
            started.set();release.wait(2)
            return {"choices":[{"message":{"content":"[0]"}}]}
        try:
            with patch(MODULE,side_effect=slow) as provider:
                t=time.monotonic()
                result=engine.answer("?",[row(1,"原句。")])
                self.assertLess(time.monotonic()-t,.4)
                self.assertEqual(result["mode"],"keyword")
                self.assertTrue(started.is_set())
                busy=engine.answer("?",[row(1,"原句。")])
                self.assertEqual(busy["reason"],"模型繁忙")
                self.assertEqual(provider.call_count,1)
                release.set()
                self.assertTrue(engine.slots.acquire(timeout=1))
                engine.slots.release()
                self.assertEqual(result["mode"],"keyword")
        finally:release.set()

    def test_start_failure_returns_slot(self):
        engine=CommunityAnswers(lambda:{"model":"test"},1,1)
        with patch("rag_tech_retriever.platform.community_answers.Thread.start",side_effect=RuntimeError("failed")):
            self.assertEqual(engine.answer("?",[row(1,"原句。")])["mode"],"keyword")
        self.assertTrue(engine.slots.acquire(blocking=False))
        engine.slots.release()

class OutputBudgetContract(unittest.TestCase):
    def test_budget_is_bounded_and_passed_to_provider(self):
        for invalid in (0,4097):
            with self.assertRaises(ValueError):CommunityAnswers(dict,1,1,invalid)
        engine=CommunityAnswers(lambda:{"model":"test"},1,1,512)
        def respond(config,payload,*args):
            self.assertEqual(payload["max_tokens"],512)
            return {"choices":[{"message":{"content":"[0]"},"finish_reason":"stop"}]}
        with patch(MODULE,side_effect=respond):
            self.assertEqual(engine.answer("?",[row(1,"原句。")])["mode"],"ai_evidence")

    def test_reasoning_exhaustion_has_explicit_code_and_no_fabricated_quote(self):
        engine=CommunityAnswers(lambda:{"model":"test"},1,1)
        raw={"choices":[{"message":{"content":"","reasoning_content":"private model reasoning"},"finish_reason":"length"}]}
        with patch(MODULE,return_value=raw):
            result=engine.answer("?",[row(1,"原句。")])
        self.assertEqual(result["reason_code"],"output_limit")
        self.assertNotIn("private model reasoning",json.dumps(result))
        self.assertEqual(result["evidence"][0]["quote"],"原句。")

    def test_auth_error_never_discloses_provider_body(self):
        from rag_tech_retriever.common.provider import ProviderError
        engine=CommunityAnswers(lambda:{"model":"test"},1,1)
        with patch(MODULE,side_effect=ProviderError("sensitive upstream body",status=401)):
            result=engine.answer("?",[row(1,"原句。")])
        self.assertEqual(result["reason_code"],"provider_auth")
        self.assertNotIn("sensitive upstream body",json.dumps(result))

if __name__=="__main__":unittest.main()
