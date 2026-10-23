"""C-16 research, C-17 options, C-20 code/research tools -- through the real gateway path.

test.run executes real subprocesses; url.read reads a real local HTTP server on 127.0.0.1.
"""
import http.server
import json
import threading
import unittest
from pathlib import Path

from maep.authority.canonical_source import CanonicalManifest
from maep.core import MAEPError
from maep.tests.test_canonical_source import MAIN_SHA, FakeGitHub, manifest
from hg.brain.planner import StructuredGoalPlanner
from hg.brain.providers import ModelRouter
from hg.memory.store import MemoryStore
from hg.research.options import OptionGenerator, proposals_from_model
from hg.research.research import Researcher, documents_from_outcomes, to_memory
from hg.runtime import build_runtime
from hg.tests.fakes import ScriptedProvider
from hg.tests.support import NOW, PRINCIPAL, TempDirMixin, make_task
from hg.tools.code import TestRunAdapter

PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertEqual(1, 2)\n"
SLOW = "import time, unittest\nclass T(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(5)\n"


def grants_for(steps, task_id="T-1"):
    from datetime import timedelta
    return [{"authorization_id": s["authorization_id"], "principal": PRINCIPAL, "action": s["action"],
             "resource": s["resource"], "scope": s["scope"], "conditions": [], "task_id": task_id,
             "policy_version": "MAEP-1.1.0", "decision": "ALLOW", "issued_at": (NOW - timedelta(hours=1)).isoformat(),
             "expires_at": (NOW + timedelta(hours=2)).isoformat()} for s in steps]


class ToolBase(TempDirMixin):
    def plan(self, goal, task=None, extra_adapters=()):
        planning = build_runtime(Path(self.tmp) / "planning", [], allow_fixture_grants=True,
                                 extra_adapters=extra_adapters)
        return StructuredGoalPlanner().plan(task or make_task(), goal, planning.gateway)

    def run_goal(self, goal, *, task=None, verifiers=None, extra_adapters=()):
        task = task or make_task()
        steps = self.plan(goal, task, extra_adapters=[type(a)(Path(self.tmp) / "planning" / "root") for a in extra_adapters])
        rt = self.build(grants_for(steps, task["task_id"]), verifiers=verifiers or {}, extra_adapters=extra_adapters)
        final = rt.orch.execute_task(task, steps)
        return rt, final

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class CodeToolTests(ToolBase):
    def test_search_symbols_and_diff_through_the_gateway(self):
        self.put("out/src/app.py", "def greet(name):\n    return helper(name)\n\nclass Box:\n    def open(self):\n        pass\n")
        def check(snapshot):
            obs = {o["tool"]: o["observed"] for o in snapshot["outcomes"]}
            ok = (obs["code.search"]["match_count"] == 1 and
                  {s["qualname"] for s in obs["code.symbols"]["symbols"]} == {"greet", "Box", "Box.open"} and
                  obs["code.diff"]["added"] == 5)
            return ok, json.dumps({k: v.get("match_count", v.get("symbol_count", v.get("added"))) for k, v in obs.items()})
        rt, final = self.run_goal({"operations": [{"op": "search", "path": "out/src", "pattern": "helper("},
                                                  {"op": "symbols", "path": "out/src"},
                                                  {"op": "diff", "path": "out/src/app.py", "against": "def greet(name):\n"}]},
                                  verifiers={"AC-1": check})
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        completed = rt.actions.events("ACTION_COMPLETED")
        self.assertNotIn("matches", completed[0]["payload"]["observed"])       # bulky output stays out of the ledger

    def test_passing_tests_verify(self):
        self.put("out/tests/test_ok.py", PASSING)
        rt, final = self.run_goal({"operations": [{"op": "test", "path": "out/tests"}]},
                                  verifiers={"AC-1": lambda s: (s["outcomes"][0]["observed"]["ok"], "ok flag")})
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(rt.actions.events("ACTION_STARTED")[0]["payload"]["request"]["action"], "EXECUTE")

    def test_failing_tests_do_not_close(self):
        self.put("out/tests/test_bad.py", FAILING)
        _rt, final = self.run_goal({"operations": [{"op": "test", "path": "out/tests"}]},
                                   verifiers={"AC-1": lambda s: (s["outcomes"][0]["observed"]["ok"], "ok flag")})
        self.assertEqual(final["task"]["state"], "UNVERIFIED")

    def test_interrupted_test_run_stays_unknown_and_blocks(self):
        class QuickTimeout(TestRunAdapter):
            name = "test.quick"
            timeout_s = 6
        self.put("out/tests/test_slow.py", SLOW)
        rt, final = self.run_goal({"operations": [{"tool": "test.quick", "params": {"path": "out/tests"}}]},
                                  extra_adapters=[QuickTimeout(self.root)])
        self.assertEqual(final["task"]["state"], "BLOCKED")
        action = rt.gateway.pending_actions("T-1")[0]["action_id"]
        self.assertEqual(rt.gateway.reconcile(action)["finding"], "UNKNOWN")    # cannot be inspected; stays blocked

    def test_test_run_declares_its_risk(self):
        rt = self.build([])
        entry = next(t for t in rt.gateway.registry() if t["name"] == "test.run")
        self.assertEqual((entry["action"], entry["idempotent"], entry["risk"]), ("EXECUTE", False, "HIGH"))

    def test_test_run_requires_execute_permission(self):
        self.put("out/tests/test_ok.py", PASSING)
        steps = self.plan({"operations": [{"op": "test", "path": "out/tests"}]})
        wrong = grants_for(steps)
        wrong[0]["action"] = "READ"                                 # a READ grant does not cover EXECUTE
        rt = self.build(wrong)
        self.assertEqual(rt.orch.execute_task(make_task(), steps)["task"]["state"], "PLANNED")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"HG research page. timeout = 30" if self.path != "/missing" else b"no"
        self.send_response(200 if self.path != "/missing" else 404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class UrlReadTests(ToolBase):
    def setUp(self):
        super().setUp()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def url_task(self):
        task = make_task()
        task["scope"]["include"] = [self.base]
        return task

    def test_read_through_gateway_keeps_text_out_of_ledger(self):
        task = self.url_task()
        rt, final = self.run_goal({"operations": [{"op": "fetch", "url": self.base + "page"}]}, task=task,
                                  verifiers={"AC-1": lambda s: ("timeout = 30" in s["outcomes"][0]["observed"]["text"], "")})
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertNotIn("text", rt.actions.events("ACTION_COMPLETED")[0]["payload"]["observed"])

    def test_http_error_is_a_known_failure(self):
        _rt, final = self.run_goal({"operations": [{"op": "fetch", "url": self.base + "missing"}]}, task=self.url_task())
        self.assertEqual(final["task"]["state"], "BLOCKED")

    def test_credentials_in_url_rejected_even_inside_scope(self):
        from hg.brain.planner import PlanRejected
        inside = self.base.replace("http://", "http://user:pw@") + "page"
        with self.assertRaisesRegex(PlanRejected, "credentials"):
            self.plan({"operations": [{"op": "fetch", "url": inside}]}, self.url_task())

    def test_invalid_urls_rejected_at_planning(self):
        from hg.brain.planner import PlanRejected
        for url in ("ftp://x/y", "http://user:pw@127.0.0.1/", "notaurl"):
            with self.assertRaises(PlanRejected, msg=url):
                self.plan({"operations": [{"op": "fetch", "url": url}]}, self.url_task())

    def test_anchored_runtime_denies_urls_the_manifest_does_not_list(self):
        source = CanonicalManifest.from_github(http_get=FakeGitHub(files={MAIN_SHA: manifest(
            actions=("maep.read",), scope=("file:out/",))}).get, max_age_s=0, clock=self.clock)
        rt = self.build([], authority=source, issue_task_grants=True)
        final = rt.orch.execute_goal(self.url_task(), {"operations": [{"op": "fetch", "url": self.base + "page"}]},
                                     StructuredGoalPlanner())
        self.assertEqual(final["task"]["state"], "PLANNED")
        self.assertEqual(rt.actions.events("ACTION_STARTED"), [])


DOCS = [{"ref": "file:out/a.md", "text": "The HG trust anchor lives on main. The cache timeout = 30 seconds."},
        {"ref": "file:out/b.md", "text": "Operations note: cache timeout = 60 seconds during load tests."}]


class ResearchTests(ToolBase):
    def test_claims_cite_sources_and_disagreements_are_found(self):
        record = Researcher().investigate("cache timeout", DOCS)
        self.assertTrue(all(c["source_refs"] and c["claim_type"] == "INFERENCE" for c in record["claims"]))
        self.assertEqual(record["disagreements"], [{"key": "timeout", "values": {"S1": "30", "S2": "60"}}])
        self.assertEqual([s["ref"] for s in record["sources"]], ["file:out/a.md", "file:out/b.md"])

    def test_gaps_and_no_match(self):
        record = Researcher().investigate("quantum flux", DOCS)
        self.assertEqual(record["gaps"], ["flux", "quantum"])
        self.assertEqual(record["claims"][0]["claim_id"], "C0")

    def test_summary_kept_only_with_valid_citations(self):
        good = ScriptedProvider("m", ["Timeout differs: 30s [S1] vs 60s [S2]."])
        rec = Researcher(ModelRouter([good], sleep=lambda s: None)).investigate("cache timeout", DOCS, summarize=True)
        self.assertEqual(rec["summary_citations"], ["S1", "S2"])
        for text, note in (("Made up [S9].", "unknown sources"), ("No citations at all.", "no citations")):
            bad = ScriptedProvider("m", [text])
            rec = Researcher(ModelRouter([bad], sleep=lambda s: None)).investigate("cache timeout", DOCS, summarize=True)
            self.assertIsNone(rec["summary"])
            self.assertIn(note, rec["summary_note"])

    def test_documents_come_from_gateway_outcomes(self):
        self.put("out/a.md", DOCS[0]["text"])
        self.put("out/b.md", DOCS[1]["text"])
        rt, final = self.run_goal({"operations": [{"op": "read", "path": "out/a.md"}, {"op": "read", "path": "out/b.md"}]},
                                  verifiers={"AC-1": lambda s: (len(documents_from_outcomes(s["outcomes"])) == 2, "")})
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        record = Researcher().investigate("cache timeout", documents_from_outcomes(rt.orch._outcomes["T-1"]))
        self.assertEqual(len(record["disagreements"]), 1)

    def test_findings_stored_as_hypotheses_not_facts(self):
        memory = MemoryStore(Path(self.tmp) / "memory.jsonl", clock=self.clock)
        stored = to_memory(Researcher().investigate("cache timeout", DOCS), memory, task_id="T-1")
        self.assertTrue(stored and all(m["kind"] == "HYPOTHESIS" and m["evidence_refs"] for m in stored))

    def test_research_requires_gateway_documents(self):
        with self.assertRaises(MAEPError):
            Researcher().investigate("q", [{"path": "/etc/passwd"}])


class OptionTests(unittest.TestCase):
    def setUp(self):
        self.gen = OptionGenerator()
        self.rubric = {"value": 2, "cost": 1}
        self.scorers = {"value": lambda o: {"local": 0.6, "remote": 0.9}[o["model"]],
                        "cost": lambda o: {"local": 1.0, "remote": 0.2}[o["model"]] * (0.5 if o["memory"] == "vector" else 1.0)}

    def test_rubric_ranks_and_constraints_reject(self):
        result = self.gen.generate(rubric=self.rubric, scorers=self.scorers,
                                   dimensions={"model": ["local", "remote"], "memory": ["bm25", "vector"]},
                                   constraints=[("offline", lambda o: o["model"] == "local" or o["memory"] == "bm25")])
        self.assertEqual(result["evaluated"], 4)
        self.assertEqual(result["feasible"], 3)
        self.assertEqual(result["options"][0]["option"], {"memory": "bm25", "model": "local"})
        self.assertEqual(result["rejected"][0]["reason"], "constraints failed: offline")

    def test_bad_scores_reject_the_option(self):
        result = self.gen.generate(rubric={"value": 1}, scorers={"value": lambda o: 1.5 if o["x"] == 1 else 0.5},
                                   dimensions={"x": [1, 2]})
        self.assertEqual((result["feasible"], "not a number in [0, 1]" in result["rejected"][0]["reason"]), (1, True))
        crash = self.gen.generate(rubric={"value": 1}, scorers={"value": lambda o: 1 / 0}, dimensions={"x": [1]})
        self.assertIn("raised ZeroDivisionError", crash["rejected"][0]["reason"])

    def test_self_assessment_ignored_and_duplicates_merged(self):
        result = self.gen.generate(rubric={"value": 1}, scorers={"value": lambda o: 0.5},
                                   proposals=[{"model": "local", "score": 99, "rationale": "best ever"},
                                              {"model": "local"}])
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(result["options"][0]["scores"], {"value": 0.5})

    def test_novelty_relative_to_baseline(self):
        result = self.gen.generate(rubric={"novelty": 1}, scorers={}, baseline={"a": 1, "b": 1},
                                   dimensions={"a": [1, 2], "b": [1]})
        self.assertEqual([o["total"] for o in result["options"]], [0.5, 0.0])

    def test_configuration_errors(self):
        with self.assertRaises(MAEPError):
            self.gen.generate(rubric={}, scorers={}, dimensions={"a": [1]})
        with self.assertRaises(MAEPError):
            self.gen.generate(rubric={"value": 1}, scorers={}, dimensions={"a": [1]})
        with self.assertRaises(MAEPError):
            self.gen.generate(rubric={"value": -1}, scorers={"value": lambda o: 1}, dimensions={"a": [1]})

    def test_design_space_is_bounded(self):
        result = OptionGenerator(max_combinations=5).generate(rubric={"v": 1}, scorers={"v": lambda o: 0.1},
                                                             dimensions={"a": list(range(10)), "b": list(range(10))})
        self.assertEqual((result["evaluated"], result["truncated"]), (5, True))

    def test_model_proposals_parsed_or_empty(self):
        router = ModelRouter([ScriptedProvider("m", ['[{"model": "local"}, 3, {}]', "nonsense"])], sleep=lambda s: None)
        self.assertEqual(proposals_from_model(router, "pick a model"), [{"model": "local"}])
        self.assertEqual(proposals_from_model(router, "again"), [])


if __name__ == "__main__":
    unittest.main()
