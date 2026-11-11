"""WS-04 model plan read oracle: a model's plan text has one reading, or it is no plan.

A model's answer is untrusted data (MAEP-019). ModelPlanner turns it into steps that HG
authorizes and runs, so the answer must be read the same way by every reader: a repeated
key, a non-standard number or a string that cannot be written as UTF-8 is refused as a
plan problem (PlanRejected), not read last-value-wins, not carried into the ledger, and
not raised as a raw exception. Parameters that no adapter can act on (NUL in a path, an
invalid URL port) are plan problems too, for any planner.

Each case is exact text from a scripted provider; each must finish within 5 s.
"""
import time
import unittest

from hg.brain.planner import ModelPlanner, PlanRejected, StructuredGoalPlanner
from hg.brain.providers import ModelRouter
from hg.http_api import HTTPBoundaryError, strict_json
from hg.research.options import proposals_from_model
from hg.tests.fakes import ScriptedProvider
from hg.tests.support import TempDirMixin, grant, make_task

GOOD = '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","content":"xin chao"}}]}'

AMBIGUOUS = {
    # fs.read first, fs.write last: last-value-wins turned a read into a write.
    "repeated tool": '{"steps":[{"tool":"fs.read","params":{"path":"out/hello.txt"},'
                     '"tool":"fs.write","params":{"path":"out/hello.txt","content":"x"}}]}',
    "repeated steps": '{"steps":[{"tool":"fs.read","params":{"path":"out/hello.txt"}}],'
                      '"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","content":"x"}}]}',
    "repeated param": '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","path":"out/b.txt",'
                      '"content":"x"}}]}',
    "NaN": '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","content":"x"}}],"n":NaN}',
    "Infinity": '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","content":"x"}}],"n":-Infinity}',
    "lone surrogate in content": '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt",'
                                 '"content":"a\\ud800"}}]}',
    "lone surrogate in path": '{"steps":[{"tool":"fs.write","params":{"path":"out/\\udc00.txt","content":"x"}}]}',
    "lone surrogate in key": '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","content":"x"}}],'
                             '"\\ud800":1}',
    "NUL in path": '{"steps":[{"tool":"fs.write","params":{"path":"out/a\\u0000.txt","content":"x"}}]}',
    "invalid url port": '{"steps":[{"tool":"url.read","params":{"url":"https://example.com:99999/x"}}]}',
}


def router(*script):
    return ModelRouter([ScriptedProvider("scripted", list(script))], sleep=lambda s: None)


class ModelPlanReadOracle(TempDirMixin):
    def setUp(self):
        super().setUp()
        self.rt = self.build([])

    def test_ambiguous_or_unwritable_plan_is_a_plan_problem(self):
        for name, text in AMBIGUOUS.items():
            with self.subTest(name):
                started = time.monotonic()
                with self.assertRaises(PlanRejected):
                    ModelPlanner(router(text, text, text)).plan(make_task(), "g", self.rt.gateway)
                self.assertLess(time.monotonic() - started, 5)

    def test_problem_is_fed_back_and_a_clean_revision_is_accepted(self):
        provider = ScriptedProvider("scripted", [AMBIGUOUS["repeated tool"], GOOD])
        planner = ModelPlanner(ModelRouter([provider], sleep=lambda s: None))
        steps = planner.plan(make_task(), "g", self.rt.gateway)
        self.assertEqual([(s["tool"], s["action"]) for s in steps], [("fs.write", "WRITE")])
        self.assertIn("repeated JSON key", provider.requests[1]["messages"][-1]["content"])

    def test_control_canonical_plan_still_accepted(self):
        steps = ModelPlanner(router(GOOD)).plan(make_task(), "g", self.rt.gateway)
        self.assertEqual(steps[0]["params"], {"path": "out/hello.txt", "content": "xin chao"})
        # Exact CR and non-ASCII content are valid text and stay as written.
        text = '{"steps":[{"tool":"fs.write","params":{"path":"out/hello.txt","content":"a\\r\\nb \\u00e9 \\ud83d\\ude00"}}]}'
        steps = ModelPlanner(router(text)).plan(make_task(), "g", self.rt.gateway)
        self.assertEqual(steps[0]["params"]["content"], "a\r\nb é \U0001F600")


class ModelPlanRuntimeOracle(TempDirMixin):
    """Through execute_goal: no raw exception, no effect, the problem kept as evidence."""

    def test_unwritable_or_ambiguous_plan_ends_assessed_without_effect(self):
        for index, name in enumerate(["lone surrogate in content", "repeated tool", "NUL in path"], 1):
            with self.subTest(name):
                rt = self.build([grant(f"T-{index}/S-1")])
                text = AMBIGUOUS[name]
                final = rt.orch.execute_goal(make_task(task_id=f"T-{index}"), "g",
                                             ModelPlanner(router(text, text, text)))
                self.assertEqual(final["task"]["state"], "ASSESSED")
                results = [e["result"] for e in final["evidence"].values()]
                self.assertTrue(any(r.startswith("PLAN_REJECTED") for r in results), results)
                self.assertFalse((self.root / "out").exists() and any((self.root / "out").iterdir()))

    def test_control_clean_plan_still_closes(self):
        rt = self.build([grant("T-1/S-1")])
        final = rt.orch.execute_goal(make_task(), "g", ModelPlanner(router(GOOD)))
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")


class StructuredPlanParamsOracle(TempDirMixin):
    """Parameters no adapter can act on are plan problems for the offline planner too."""

    def test_unusable_params_rejected(self):
        rt = self.build([])
        for name, op in {"NUL in path": {"op": "write", "path": "out/a\x00.txt", "content": "x"},
                         "lone surrogate in path": {"op": "write", "path": "out/\ud800.txt", "content": "x"},
                         "lone surrogate in content": {"op": "write", "path": "out/a.txt", "content": "\udfff"},
                         "invalid url port": {"op": "fetch", "url": "http://example.com:70000/"}}.items():
            with self.subTest(name):
                with self.assertRaises(PlanRejected):
                    StructuredGoalPlanner().plan(make_task(), {"operations": [op]}, rt.gateway)


class ModelOptionsOracle(unittest.TestCase):
    def test_ambiguous_options_yield_nothing(self):
        for name, text in {"repeated key": '[{"name":"a","name":"b"}]',
                           "NaN": '[{"name":"a","cost":NaN}]',
                           "lone surrogate": '[{"name":"\\ud800"}]'}.items():
            with self.subTest(name):
                self.assertEqual(proposals_from_model(router(text), "brief"), [])

    def test_control_options_read(self):
        self.assertEqual(proposals_from_model(router('Here: [{"name":"a"},{"name":"b"}]'), "brief"),
                         [{"name": "a"}, {"name": "b"}])


class HTTPBodyTextOracle(unittest.TestCase):
    def test_lone_surrogate_body_is_invalid_json_not_internal_error(self):
        for body in (b'{"a":"\\ud800"}', b'{"\\udc00":1}', b'["x\\ud83d"]'):
            with self.subTest(body):
                with self.assertRaises(HTTPBoundaryError) as ctx:
                    strict_json(body)
                self.assertEqual(ctx.exception.status, 400)

    def test_control_paired_surrogate_escape_reads(self):
        self.assertEqual(strict_json(b'{"a":"\\ud83d\\ude00"}'), {"a": "\U0001F600"})


if __name__ == "__main__":
    unittest.main()
