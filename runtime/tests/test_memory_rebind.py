"""N10: verified Memory restore and explicit, owner-approved store rebind.

Exact resource/scope matching and the store-location binding (MAEP-004) are unchanged.
These tests prove, through compose_service and real HTTP, that:
  * a restore to a new path grants nothing until the owner approves a rebound policy
    AND issues a rebound session (no automatic re-grant at any step);
  * after both, access works again and stays exact (unlisted resource, wrong
    credential and scope mismatch are still refused);
  * restoring to the original location after loss needs no rebind;
  * corrupted, tampered or overwriting restores are refused and create nothing usable.
Everything runs in a temporary directory with test-only D2/D4 fixtures.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from maep.local_runtime_providers import _digest, _write_new_json
from memory import AuthorityEvidenceReader, MemoryStore
from runtime import memory_rebind
from runtime.errors import RuntimeStartupError
from runtime.production_config import compose_service
from runtime.session_auth import TokenSessionSource, issue_session

fixture = __import__("e2e_fixture_factory")
composition = __import__("test_production_composition_e2e")


def provisioner(db):
    return MemoryStore(db, principal_provider=lambda: "provisioner",
                       policy_evaluator=fixture.store_fixtures.policy_decision,
                       applicability_provider=fixture.store_fixtures.applicability_provider_for_test)


class RestoreRebindE2ETests(composition.CompositionE2ETests):
    for _name in [n for n in dir(composition.CompositionE2ETests) if n.startswith("test_")]:
        locals()[_name] = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-e2e-n10-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = fixture.provision(self.tmp.name, memory_rules=True)
        self.config = self.state["config"]
        self.old_db = str(Path(self.config["memory_db"]).absolute())
        self.token = Path(self.state["token_path"]).read_text().strip()
        self.session = TokenSessionSource(**self.state["session"])
        self.backup = self.base / "backup" / "hg.sqlite3"
        self.backup.parent.mkdir(mode=0o700)
        provisioner(self.old_db).backup_to(self.backup, task_id=fixture.READ_TASK)

    def owner_approves(self, proposal_path, approved_path, *, refs=("owner:rebind-approval",)):
        """TEST-ONLY stand-in for the owner's D2 approval of a rebind proposal."""
        proposed = json.loads(Path(proposal_path).read_text())["policy"]
        policy = dict(proposed, status="ACTIVE", approval_evidence_refs=list(refs))
        _write_new_json(Path(approved_path), {"policy": policy, "policy_digest": _digest(policy),
                                              "fixture_approval": "test-only-not-production"})
        return str(approved_path)

    def rebound_session(self, new_db):
        grants = memory_rebind.session_scopes(session_path=self.state["session"]["session_path"],
                                              old_store=self.old_db, new_store=new_db)
        paths = {"session_path": str(self.base / "session2" / "session.json"),
                 "revocation_path": str(self.base / "session2" / "revocations.json")}
        issue_session(session_path=paths["session_path"], token_path=self.base / "session2" / "token",
                      revocation_path=paths["revocation_path"], principal_id=grants["principal_id"],
                      valid_days=1, capabilities=grants["capabilities"],
                      resource_scopes=grants["resource_scopes"], allowed_scopes=grants["allowed_scopes"])
        return TokenSessionSource(**paths), (self.base / "session2" / "token").read_text().strip()

    def restore_new(self):
        new_db = str(self.base / "restored" / "hg.sqlite3")
        result = memory_rebind.restore(self.backup, new_db)
        return new_db, result

    def test_restore_grants_nothing_until_owner_rebinds_policy_and_session(self):
        new_db, result = self.restore_new()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source_snapshot"], result["restored_snapshot"])
        self.assertEqual(os.stat(new_db).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(result["manifest_path"]).st_mode & 0o777, 0o600)

        # 1. Restored store under the unchanged policy and session: nothing authorized.
        self.config = dict(self.config, memory_db=new_db)
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 403, body)
        self.assertNotIn(("authorization.decision", ["AUTHORIZED"]), self.decisions())

        # 2. The rebind proposal is inactive and unapproved; even with the D2 fixture
        #    marker added it cannot be loaded.
        proposal = str(self.base / "policy.rebind-proposal.json")
        out = memory_rebind.propose_policy(policy_path=self.config["policy_path"], old_store=self.old_db,
                                           new_store=new_db, manifest_path=result["manifest_path"],
                                           out_path=proposal)
        self.assertEqual(out["status"], "PROPOSED")
        doc = json.loads(Path(proposal).read_text())
        self.assertNotIn("fixture_approval", doc)
        self.assertEqual((doc["policy"]["status"], doc["policy"]["approval_evidence_refs"]), ("PROPOSED", []))
        self.assertFalse(any(self.old_db in json.dumps(rule) for rule in doc["policy"]["rules"]))
        marked = dict(doc, fixture_approval="test-only-not-production")
        _write_new_json(self.base / "policy.marked.json", marked)
        with self.assertRaisesRegex(RuntimeStartupError, "production composition blocked"):
            compose_service(dict(self.config, policy_path=str(self.base / "policy.marked.json")),
                            fixture.bindings(self.session, self.config))
        unapproved = self.owner_approves(proposal, self.base / "policy.no-refs.json", refs=())
        with self.assertRaisesRegex(RuntimeStartupError, "production composition blocked"):
            compose_service(dict(self.config, policy_path=unapproved), fixture.bindings(self.session, self.config))

        # 3. Owner-approved rebound policy, OLD session: still denied (session not rebound).
        self.config = dict(self.config, policy_path=self.owner_approves(proposal, self.base / "policy.rebound.json"))
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions()[-1], ("authorization.deny", ["PRINCIPAL_SCOPE_DENIED"]))

        # 4. Owner issues a rebound session: access returns, still exact.
        old_token = self.token
        self.session, self.token = self.rebound_session(new_db)
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 200, body)
        task = fixture.store_fixtures.MemoryStoreTests.task(fixture.NEW_TASK)
        self.assertEqual(self.call(server, "POST", "/api/tasks", body={"task": task})[0], 200)
        self.assertIn(fixture.NEW_TASK, AuthorityEvidenceReader(new_db).list_canonical_task_ids())
        self.assertNotIn(fixture.NEW_TASK, AuthorityEvidenceReader(self.old_db).list_canonical_task_ids())
        # wrong resource (not listed), wrong credential, scope mismatch
        self.assertEqual(self.call(server, "GET", f"/api/tasks/{fixture.UNLISTED_TASK}")[0], 403)
        self.assertEqual(self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}", token=old_token)[0], 401)
        request = {"task_ref": fixture.RUN_EXEC_TASK, "action": fixture.DISPATCH_ACTION,
                   "resource": fixture.DISPATCH_RESOURCE, "scope": ["tool:fixture:other"]}
        status, body = self.call(server, "POST", "/api/dispatch",
                                 body={"request": request, "adapter_name": "fixture", "idempotency_key": "n10-k"})
        self.assertEqual(status, 403, body)
        self.assertEqual(adapter.calls, 0)

    def test_restore_to_the_original_location_after_loss_needs_no_rebind(self):
        lost = self.base / "lost"
        lost.mkdir(mode=0o700)
        os.replace(self.old_db, lost / "hg.sqlite3")        # the database is gone from its location
        with self.assertRaises(RuntimeStartupError):
            compose_service(self.config, fixture.bindings(self.session, self.config))
        result = memory_rebind.restore(self.backup, self.old_db)
        self.assertEqual(result["status"], "PASS")
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 200, body)


class RestoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-n10-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = fixture.provision(self.base / "state", memory_rules=True)
        self.db = str(Path(self.state["config"]["memory_db"]).absolute())
        self.backup = self.base / "backup.sqlite3"
        provisioner(self.db).backup_to(self.backup, task_id=fixture.READ_TASK)

    def assert_nothing_created(self, target):
        target = Path(target)
        self.assertFalse(target.exists())
        self.assertFalse(Path(str(target) + ".restore-manifest.json").exists())
        if target.parent.exists():
            self.assertEqual([p for p in target.parent.iterdir() if p.name.endswith(".partial")], [])

    def test_tampered_event_chain_is_refused(self):
        connection = sqlite3.connect(self.backup)
        triggers = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
        for name in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("UPDATE maep_events SET payload_json='{\"forged\":true}' WHERE sequence=1")
        connection.commit()
        connection.close()
        target = self.base / "out" / "hg.sqlite3"
        with self.assertRaisesRegex(memory_rebind.RebindError, "integrity|invalid"):
            memory_rebind.restore(self.backup, target)
        self.assert_nothing_created(target)

    def test_non_database_and_broad_permission_backups_are_refused(self):
        garbage = self.base / "garbage.sqlite3"
        garbage.write_bytes(b"not a database" * 100)
        os.chmod(garbage, 0o600)
        with self.assertRaises(memory_rebind.RebindError):
            memory_rebind.restore(garbage, self.base / "g" / "hg.sqlite3")
        self.assert_nothing_created(self.base / "g" / "hg.sqlite3")
        os.chmod(self.backup, 0o644)
        with self.assertRaises(memory_rebind.RebindError):
            memory_rebind.restore(self.backup, self.base / "p" / "hg.sqlite3")
        self.assert_nothing_created(self.base / "p" / "hg.sqlite3")

    def test_existing_target_manifest_or_journal_is_never_overwritten(self):
        target = self.base / "t" / "hg.sqlite3"
        target.parent.mkdir(mode=0o700)
        for suffix in ("", ".restore-manifest.json", "-journal"):
            path = Path(str(target) + suffix)
            path.write_bytes(b"keep")
            with self.assertRaisesRegex(memory_rebind.RebindError, "refusing"):
                memory_rebind.restore(self.backup, target)
            self.assertEqual(path.read_bytes(), b"keep")
            path.unlink()
        with self.assertRaisesRegex(memory_rebind.RebindError, "differ"):
            memory_rebind.restore(self.backup, self.backup)

    def test_policy_proposal_refuses_unverified_or_ambiguous_input(self):
        new_db = str(self.base / "r" / "hg.sqlite3")
        manifest = memory_rebind.restore(self.backup, new_db)["manifest_path"]
        policy_path = self.state["config"]["policy_path"]
        kwargs = dict(policy_path=policy_path, old_store=self.db, new_store=new_db, manifest_path=manifest)
        n = iter(range(100))

        def out():
            return str(self.base / f"proposal-{next(n)}.json")

        with self.assertRaisesRegex(memory_rebind.RebindError, "differ"):
            memory_rebind.propose_policy(**dict(kwargs, new_store=self.db), out_path=out())
        with self.assertRaisesRegex(memory_rebind.RebindError, "does not describe"):
            memory_rebind.propose_policy(**dict(kwargs, new_store=str(self.base / "x.sqlite3")), out_path=out())
        # wrong old store: the policy's resources name a store that is neither old nor new
        with self.assertRaisesRegex(memory_rebind.RebindError, "another store"):
            memory_rebind.propose_policy(**dict(kwargs, old_store=str(self.base / "y.sqlite3")), out_path=out())
        raw_policy = json.loads(Path(policy_path).read_text())["policy"]
        tool_only = dict(raw_policy, rules=[r for r in raw_policy["rules"] if "[store:" not in r["resource"]])
        tool_only_path = self.base / "tool-only.json"
        _write_new_json(tool_only_path, {"policy": tool_only, "policy_digest": _digest(tool_only)})
        with self.assertRaisesRegex(memory_rebind.RebindError, "nothing to rebind"):
            memory_rebind.propose_policy(**dict(kwargs, policy_path=str(tool_only_path)), out_path=out())
        with self.assertRaisesRegex(memory_rebind.RebindError, "new file"):
            memory_rebind.propose_policy(**kwargs, out_path=policy_path)
        existing = out()
        Path(existing).write_text("{}")
        with self.assertRaisesRegex(Exception, "overwrite"):
            memory_rebind.propose_policy(**kwargs, out_path=existing)
        # policy that also names a third store -> ambiguous
        raw = json.loads(Path(policy_path).read_text())
        third = dict(raw["policy"], rules=raw["policy"]["rules"] + [
            {"action": "READ", "resource": "memory:task/X [store:/elsewhere/hg.sqlite3]",
             "scope": ["memory:task:X:read"], "effect": "ALLOW"}])
        third_path = self.base / "third.json"
        _write_new_json(third_path, {"policy": third, "policy_digest": _digest(third)})
        with self.assertRaisesRegex(memory_rebind.RebindError, "another store"):
            memory_rebind.propose_policy(**dict(kwargs, policy_path=str(third_path)), out_path=out())
        # tampered policy document (digest no longer matches)
        forged = self.base / "forged.json"
        _write_new_json(forged, dict(raw, policy=dict(raw["policy"], status="PROPOSED")))
        with self.assertRaisesRegex(memory_rebind.RebindError, "digest"):
            memory_rebind.propose_policy(**dict(kwargs, policy_path=str(forged)), out_path=out())
        # restored store changed after verification
        provisioner(new_db).record_evidence(fixture.READ_TASK, fixture.store_fixtures.MemoryStoreTests.evidence(
            "EV-AFTER-RESTORE", self.state["candidate_ref"]))
        with self.assertRaisesRegex(memory_rebind.RebindError, "changed since"):
            memory_rebind.propose_policy(**kwargs, out_path=out())

    def test_session_scopes_rebind_only_store_bound_entries(self):
        new_db = str(self.base / "s" / "hg.sqlite3")
        grants = memory_rebind.session_scopes(session_path=self.state["session"]["session_path"],
                                              old_store=self.db, new_store=new_db)
        record = json.loads(Path(self.state["session"]["session_path"]).read_text())
        self.assertEqual(len(grants["resource_scopes"]), len(record["resource_scopes"]))
        self.assertIn(fixture.DISPATCH_RESOURCE, grants["resource_scopes"])
        self.assertFalse(any(self.db in scope for scope in grants["resource_scopes"]))
        self.assertEqual(grants["allowed_scopes"], record["allowed_scopes"])
        self.assertNotIn("token_sha256", json.dumps(grants))
        with self.assertRaisesRegex(memory_rebind.RebindError, "differ"):
            memory_rebind.session_scopes(session_path=self.state["session"]["session_path"],
                                         old_store=self.db, new_store=self.db)

    def test_cli_reports_and_blocks_without_secrets(self):
        token = Path(self.state["token_path"]).read_text().strip()
        stdout, stderr = io.StringIO(), io.StringIO()
        target = str(self.base / "cli" / "hg.sqlite3")
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(memory_rebind.main(["restore", "--backup", str(self.backup), "--target", target]), 0)
            self.assertEqual(memory_rebind.main(["restore", "--backup", str(self.backup), "--target", target]), 2)
            self.assertEqual(memory_rebind.main(["session-scopes", "--session", self.state["session"]["session_path"],
                                                 "--old-store", self.db, "--new-store", target]), 0)
        self.assertEqual(json.loads(stdout.getvalue().split("\n}\n")[0] + "}")["status"], "PASS")
        self.assertIn("BLOCKED:", stderr.getvalue())
        self.assertNotIn(token, stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
