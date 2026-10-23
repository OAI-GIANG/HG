"""RT-06 through the HG runtime: with authority=CanonicalManifest the trust root gates every path.

Public entry points only (BrainOrchestrator, ActionGateway, restart via build_runtime). Each
denial asserts the real filesystem effect did not happen. GitHub is simulated in-process
(FakeGitHub); the live check against main is `python -m hg authority-check`.
"""
import unittest

from maep.authority.canonical_source import CanonicalManifest
from maep.core import MAEPError
from maep.ledger import read_events
from maep.tests.test_canonical_source import FEATURE_SHA, MAIN_SHA, FakeGitHub, manifest
from hg.tools.gateway import LocalFileWriteAdapter
from hg.tests.support import TempDirMixin, grant, make_task, write_step


class CrashOnce(LocalFileWriteAdapter):
    name = "crashonce.write"
    crashes_left = 1

    def execute(self, params):
        observed = super().execute(params)
        if CrashOnce.crashes_left:
            CrashOnce.crashes_left -= 1
            raise RuntimeError("died after the write")
        return observed


class AnchoredBase(TempDirMixin):
    def setUp(self):
        super().setUp()
        CrashOnce.crashes_left = 1
        self.gh = FakeGitHub(files={MAIN_SHA: manifest()})       # STT may maep.write under file:out/

    def anchored(self, grants=(grant(),), **kwargs):
        source = CanonicalManifest.from_github(http_get=self.gh.get, max_age_s=0, clock=self.clock)
        return self.build(grants, authority=source, **kwargs)

    def target(self):
        return self.root / "out/hello.txt"

    def assertNoEffect(self, rt):
        self.assertFalse(self.target().exists())
        self.assertEqual(rt.actions.events("ACTION_STARTED"), [])


class AnchoredHappyPath(AnchoredBase):
    def test_task_closes_and_every_decision_carries_the_anchor(self):
        rt = self.anchored()
        self.assertEqual(rt.trust, "anchored")
        self.assertEqual(rt.orch.execute_task(make_task(), [write_step()])["task"]["state"], "CLOSED_VERIFIED")
        auth = [e for e in read_events(self.workdir / "tasks.jsonl") if e["type"] == "AUTHORIZATION_EVALUATED"]
        self.assertEqual(auth[0]["data"]["decision"]["anchor"]["commit"], MAIN_SHA)
        started = rt.actions.events("ACTION_STARTED")
        self.assertEqual(started[0]["payload"]["decision"]["anchor"]["commit"], MAIN_SHA)

    def test_fixture_mode_is_labelled(self):
        self.assertEqual(self.build([grant()]).trust, "fixture")


class TrustRootDenials(AnchoredBase):
    def assertStaysPlanned(self, rt):
        final = rt.orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "PLANNED")
        self.assertNoEffect(rt)
        self.assertTrue(any("trust anchor" in e["result"] for e in final["evidence"].values()))

    def test_missing_manifest_denies_even_with_a_task_grant(self):
        self.gh.files = {}
        self.assertStaysPlanned(self.anchored())

    def test_manifest_for_another_principal_denies(self):
        self.gh.files = {MAIN_SHA: manifest(principal="owner")}
        self.assertStaysPlanned(self.anchored())

    def test_manifest_without_the_action_denies(self):
        self.gh.files = {MAIN_SHA: manifest(actions=("maep.read",))}
        self.assertStaysPlanned(self.anchored())

    def test_feature_branch_manifest_is_not_a_trust_root(self):
        self.gh = FakeGitHub(refs={"main": MAIN_SHA, "rt06/trust-anchor-provider-20261023": FEATURE_SHA},
                             files={FEATURE_SHA: manifest()})
        self.assertStaysPlanned(self.anchored())

    def test_unreachable_github_denies(self):
        self.gh.raise_on = "commits/"
        self.assertStaysPlanned(self.anchored())


class RevocationAndBypass(AnchoredBase):
    def test_revocation_before_run_stops_running(self):
        rt = self.anchored()
        rt.orch.submit_task(make_task())
        rt.orch.assess("T-1")
        rt.orch.plan("T-1", [write_step()])
        rt.orch.authorize("T-1")
        self.gh.files = {}
        with self.assertRaisesRegex(MAEPError, "valid authorization required"):
            rt.orch.run("T-1")
        self.assertNoEffect(rt)

    def test_revocation_after_running_denies_at_the_tool_boundary(self):
        rt = self.anchored()
        rt.orch.submit_task(make_task())
        rt.orch.assess("T-1")
        rt.orch.plan("T-1", [write_step()])
        rt.orch.authorize("T-1")
        rt.orch._move("T-1", "RUNNING")
        self.gh.files = {MAIN_SHA: manifest(principal="someone-else")}
        outcome = rt.gateway.execute("T-1", "S-1")         # direct call, bypassing the orchestrator
        self.assertEqual(outcome["status"], "DENIED")
        self.assertIn("trust anchor", outcome["reason"])
        self.assertNoEffect(rt)

    def test_manifest_expiring_mid_task_denies(self):
        self.gh.files = {MAIN_SHA: manifest(expires="2026-10-23T08:30:00Z")}
        rt = self.anchored()
        rt.orch.submit_task(make_task())
        rt.orch.assess("T-1")
        rt.orch.plan("T-1", [write_step()])
        rt.orch.authorize("T-1")
        rt.orch._move("T-1", "RUNNING")
        self.clock.advance(minutes=31)
        self.assertEqual(rt.gateway.execute("T-1", "S-1")["status"], "DENIED")
        self.assertNoEffect(rt)


class RestartWithTrustRoot(AnchoredBase):
    def test_grant_added_on_main_later_lets_task_resume(self):
        self.gh.files = {}
        self.anchored().orch.execute_task(make_task(), [write_step()])
        self.gh.files = {MAIN_SHA: manifest()}               # owner merges the manifest
        second = self.anchored()
        self.assertEqual(second.orch.resume("T-1")["task"]["state"], "CLOSED_VERIFIED")

    def test_reopen_after_restart_needs_the_trust_root(self):
        rt = self.anchored(extra_adapters=[CrashOnce(self.root)])
        rt.orch.execute_task(make_task(), [write_step(tool="crashonce.write")])
        action_id = rt.gateway.pending_actions("T-1")[0]["action_id"]
        self.gh.files = {}                                   # trust root gone across the restart
        second = self.anchored(extra_adapters=[CrashOnce(self.root)])
        with self.assertRaisesRegex(MAEPError, "fresh authority and risk"):
            second.orch.reconcile_and_reopen("T-1", action_id, risk_reassessment="checked")
        self.assertEqual(second.store.snapshot("T-1")["task"]["state"], "BLOCKED")



class AuthorityCheckReport(unittest.TestCase):
    def test_unavailable_manifest_reports_blocked_exit_3(self):
        from hg.__main__ import authority_check
        from maep.authority.canonical_source import load_canonical_manifest
        code, report = authority_check(lambda: load_canonical_manifest(FakeGitHub(files={}).get))
        self.assertEqual((code, report["result"]), (3, "BLOCKED"))

    def test_loaded_manifest_reports_grants_and_provenance(self):
        from hg.__main__ import authority_check
        from maep.authority.canonical_source import load_canonical_manifest
        code, report = authority_check(lambda: load_canonical_manifest(FakeGitHub().get))
        self.assertEqual((code, report["provenance"]["commit"], report["grants"][0]["principal"]), (0, MAIN_SHA, "STT"))


if __name__ == "__main__":
    unittest.main()
