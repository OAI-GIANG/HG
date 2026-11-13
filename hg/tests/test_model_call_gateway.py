"""G4 conformance: every model inference call goes through hg.brain.providers.ModelRouter.

Stabilization admission (ledger §55, WS-08): this test only verifies a property of main; it adds
no capability. Two layers:

Static (whole source tree hg/ and maep/, tests excluded):
  S1  network primitives (urllib.request, http.client, socket, third-party HTTP/model SDKs) appear
      only in the allowlisted modules below, each with its reason;
  S2  model endpoint literals (/api/chat, /api/generate, /v1/messages, chat/completions, vendor
      API hosts) appear only in hg/brain/providers.py, the model transport;
  S3  every `.complete(...)` call outside providers.py is made on a router object
      (`router` / `self._router`), never on a provider.

Runtime (real code paths with a provider test double, no live model):
  R1  ask, chat (real ChatService, real OllamaProvider against a loopback fake), ModelPlanner and
      Researcher each reach the model only inside ModelRouter.complete;
  R2  negative cases: a provider's complete() called outside ModelRouter is caught by the probe,
      and the static checker flags a module that talks to a model endpoint directly.
"""
import ast
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from hg.brain.providers import ModelProvider, ModelRouter, OllamaProvider, make_request

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = "hg/brain/providers.py"
NETWORK_ALLOWLIST = {
    TRANSPORT: "model transport: the only place a provider sends HTTP",
    "hg/tools/code.py": "url.read tool adapter, gated by ActionGateway; reads URLs, never a model",
    "maep/authority/canonical_source.py": "RT-06 trust anchor: reads owner-grants.json from GitHub",
}
NETWORK_MODULES = {"urllib.request", "http.client", "socket", "requests", "httpx", "aiohttp",
                   "anthropic", "openai", "ollama", "google.generativeai"}
ENDPOINT_MARKERS = ("/api/chat", "/api/generate", "/api/embed", "/v1/messages", "chat/completions",
                    "/v1/completions", "api.anthropic.com", "api.openai.com", "api.deepseek.com")
ROUTER_RECEIVERS = {"router", "_router"}


def _sources():
    for top in ("hg", "maep"):
        for path in sorted((ROOT / top).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/tests/" in rel:
                continue
            yield rel, path.read_text(encoding="utf-8")


def violations(rel, source):
    """Return (rule, detail) pairs for one module; empty when it conforms."""
    found = []
    tree = ast.parse(source, filename=rel)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for name in names:
            if any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES) and rel not in NETWORK_ALLOWLIST:
                found.append(("S1", f"network import {name!r} outside the allowlist"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and rel != TRANSPORT:
            for marker in ENDPOINT_MARKERS:
                if marker in node.value and not _is_docstring(tree, node):
                    found.append(("S2", f"model endpoint {marker!r} outside {TRANSPORT}"))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "complete"
                and rel != TRANSPORT):
            receiver = node.func.value
            name = receiver.attr if isinstance(receiver, ast.Attribute) else getattr(receiver, "id", None)
            if name not in ROUTER_RECEIVERS:
                found.append(("S3", f".complete() on {name!r}, not on a ModelRouter"))
    return found


def _is_docstring(tree, const):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and first.value is const:
                return True
    return False


class StaticConformance(unittest.TestCase):
    def test_main_tree_conforms(self):
        report = {rel: v for rel, src in _sources() if (v := violations(rel, src))}
        self.assertEqual(report, {}, json.dumps(report, indent=1))

    def test_allowlisted_modules_exist(self):
        for rel in NETWORK_ALLOWLIST:
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_inference_call_sites_are_known(self):
        sites = sorted(rel for rel, src in _sources() if rel != TRANSPORT and ".complete(" in src)
        self.assertEqual(sites, ["hg/assistant/ask.py", "hg/assistant/summarize.py", "hg/brain/planner.py",
                                 "hg/research/options.py", "hg/research/research.py"],
                         "a new model call site needs review against this gateway test")

    # ---- negative: a module that bypasses the router is flagged for the right reasons ----
    def test_negative_direct_model_http_is_flagged(self):
        sneaky = ("import urllib.request\n"
                  "def ask_directly(q):\n"
                  "    return urllib.request.urlopen('http://127.0.0.1:11434/api/chat', data=q.encode())\n")
        rules = sorted({rule for rule, _ in violations("hg/brain/sneaky.py", sneaky)})
        self.assertEqual(rules, ["S1", "S2"])

    def test_negative_provider_complete_outside_router_is_flagged(self):
        sneaky = ("from hg.brain.providers import OllamaProvider\n"
                  "def answer(req):\n"
                  "    return OllamaProvider('m').complete(req)\n")
        self.assertEqual([r for r, _ in violations("hg/assistant/sneaky.py", sneaky)], ["S3"])


class GatewayProbe:
    """Counts router calls and refuses any provider.complete() that is not inside one."""

    def __init__(self, extra_provider_classes=()):
        self.depth = 0
        self.router_calls = 0
        self.provider_calls = []
        self._patches = []
        self._extra = extra_provider_classes

    def _provider_classes(self):
        seen, stack = [], [ModelProvider, *self._extra]
        while stack:
            cls = stack.pop()
            if cls not in seen:
                seen.append(cls)
                stack.extend(cls.__subclasses__())
        return [c for c in seen if "complete" in c.__dict__]

    def _patch(self, owner, name, value):
        self._patches.append((owner, name, owner.__dict__[name]))
        setattr(owner, name, value)

    def __enter__(self):
        probe, original = self, ModelRouter.complete

        def router_complete(router, request, **kw):
            probe.depth += 1
            probe.router_calls += 1
            try:
                return original(router, request, **kw)
            finally:
                probe.depth -= 1
        self._patch(ModelRouter, "complete", router_complete)
        for cls in self._provider_classes():
            def guarded(provider, *a, _orig=cls.__dict__["complete"], **kw):
                if probe.depth == 0:
                    raise AssertionError(f"{type(provider).__name__}.complete called outside ModelRouter.complete")
                probe.provider_calls.append(type(provider).__name__)
                return _orig(provider, *a, **kw)
            self._patch(cls, "complete", guarded)
        return self

    def __exit__(self, *exc):
        for owner, name, value in reversed(self._patches):
            setattr(owner, name, value)
        return False


class RuntimeConformance(unittest.TestCase):
    def assert_through_router(self, probe):
        self.assertGreaterEqual(probe.router_calls, 1, "no model call went through ModelRouter")
        self.assertGreaterEqual(len(probe.provider_calls), 1, "the provider was never reached")

    def test_ask_reaches_the_model_only_through_the_router(self):
        from hg.tests.test_assistant_ask import AskBase, FakeModel

        class Case(AskBase):
            def runTest(self):
                pass
        case = Case()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with GatewayProbe(extra_provider_classes=(FakeModel,)) as probe:
            code, _receipt = case.run_ask("Tôi thay dầu xe lần cuối khi nào?",
                                          model=FakeModel("Bạn thay dầu ngày 15/09/2026. [N1]"))
        self.assertEqual(code, 0)
        self.assert_through_router(probe)

    def test_chat_service_reaches_the_model_only_through_the_router(self):
        from hg.tests.test_chat_service import ChatServiceBase

        class Case(ChatServiceBase):
            def runTest(self):
                pass
        case = Case()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with GatewayProbe() as probe:
            result = case.service("Thủ đô của Pháp là gì?", general=True)
        self.assertIn("brain", result)
        self.assert_through_router(probe)
        self.assertIn("OllamaProvider", probe.provider_calls)

    def test_model_planner_reaches_the_model_only_through_the_router(self):
        from hg.brain.planner import ModelPlanner
        from hg.tests.test_planner import WRITE, ModelPlannerTests, router

        case = ModelPlannerTests("test_model_cannot_choose_resource_or_authorization")
        case.setUp()
        self.addCleanup(case.tearDown)
        with GatewayProbe() as probe:
            steps = ModelPlanner(router({"steps": [WRITE]})).plan(case.task, "write a greeting", case.rt.gateway)
        self.assertEqual(steps[0]["resource"], "file:out/hello.txt")
        self.assert_through_router(probe)

    def test_researcher_reaches_the_model_only_through_the_router(self):
        from hg.research.research import Researcher
        from hg.tests.test_research_synthesis_oracle import DOCS, router

        with GatewayProbe() as probe:
            record = Researcher(router("Timeout is 30 seconds [S1].")).investigate("cache timeout", DOCS, summarize=True)
        self.assertIsInstance(record, dict)
        self.assert_through_router(probe)

    # ---- negative: a provider called directly is caught before it can send anything ----
    def test_negative_provider_called_outside_router_is_refused(self):
        sent = []
        provider = OllamaProvider("m", http_post=lambda *a, **k: sent.append(a) or (200, {}))
        with GatewayProbe():
            with self.assertRaisesRegex(AssertionError, "OllamaProvider.complete called outside ModelRouter.complete"):
                provider.complete(make_request("s", [{"role": "user", "content": "hi"}]))
        self.assertEqual(sent, [], "the provider must be stopped before any transport call")


if __name__ == "__main__":
    unittest.main()
