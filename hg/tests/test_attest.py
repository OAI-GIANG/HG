"""Listener attestation (HG-LA-2): unit tests for parsers and policy, integration tests on the real
kernel with real processes, sockets, pidfd and pidfd_getfd.

Integration targets are copies of this interpreter named `ollama` (and `runsv` for the supervisor
stand-in), so /proc/PID/exe carries the expected names. When runit's `runsv` is on PATH the real
supervisor is used; otherwise hg/tests/fixtures/attest/runsv_double.py stands in. Only loopback
addresses and ephemeral ports are bound. HG_REQUIRE_PROC_TESTS=1 turns every environment skip into a
failure (CI sets it, so a missing capability cannot pass silently).
"""
import errno
import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from hg.assistant import attest as at
from hg.assistant import config as cfg

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "attest"
REQUIRE = os.environ.get("HG_REQUIRE_PROC_TESTS") == "1"
SUPERVISOR = "runit" if shutil.which("runsv") else "double"
LINUX = sys.platform.startswith("linux") and os.path.isdir("/proc/self/fd")


def yama_scope():
    """kernel.yama.ptrace_scope (0 when Yama is absent). At 1, pidfd_getfd needs an ancestor attester."""
    try:
        return int(Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip())
    except (OSError, ValueError):
        return 0


def _skip(reason):
    if REQUIRE:
        raise AssertionError(f"required environment missing: {reason}")
    raise unittest.SkipTest(reason)


def _wait(predicate, timeout=10.0, step=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class Lab:
    """Temporary service directories, supervisors and targets; everything is torn down."""

    def __init__(self, test):
        if not LINUX:
            _skip("Linux /proc required")
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-attest-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.procs, self.pids = [], []
        test.addCleanup(self.cleanup)
        real = os.path.realpath(sys.executable)
        (self.bin / "pyvenv.cfg").write_text(f"home = {os.path.dirname(real)}\n", encoding="utf-8")
        self.env = dict(os.environ)
        self.env.pop("PYTHONPATH", None)
        if sysconfig.get_config_var("Py_ENABLE_SHARED"):
            libdir = sysconfig.get_config_var("LIBDIR") or ""
            self.env["LD_LIBRARY_PATH"] = ":".join(p for p in (libdir, self.env.get("LD_LIBRARY_PATH", "")) if p)
        probe = subprocess.run([str(self.interpreter("ollama")), "-I", "-S", "-c", "pass"], env=self.env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        if probe.returncode:
            _skip("this interpreter cannot run from a copied path")

    def interpreter(self, name):
        target = self.bin / name
        if not target.exists():
            shutil.copy2(os.path.realpath(sys.executable), target)
            os.chmod(target, 0o755)
        return target

    def service(self, name=None):
        path = self.tmp / (name or f"svc-{uuid.uuid4().hex[:8]}")
        path.mkdir(mode=0o700)
        return path

    def start(self, mode, *, service=None, exe_name="ollama", usr1="", wrapper=False, port=0, supervisor=None,
              ptracer_any=False):
        service = service or self.service()
        ready = self.tmp / f"ready-{uuid.uuid4().hex}.json"
        cmd = [str(self.interpreter(exe_name)), "-I", "-S", str(FIXTURES / "target.py"), mode, str(ready)]
        env = dict(self.env, TARGET_USR1=usr1, TARGET_PORT=str(port), TARGET_PTRACER_ANY="1" if ptracer_any else "0")
        if (supervisor or SUPERVISOR) == "runit":
            runsv = shutil.which("runsv") or _skip("runit (runsv) not installed")
            line = " ".join(shlex.quote(c) for c in cmd)
            script = f"#!/bin/sh\n{line}\necho exited\n" if wrapper else f"#!/bin/sh\nexec {line}\n"
            (service / "run").write_text(script, encoding="utf-8")
            os.chmod(service / "run", 0o755)
            proc = subprocess.Popen([runsv, str(service)], env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        else:
            program = ["/bin/sh", "-c", " ".join(shlex.quote(c) for c in cmd) + "; true"] if wrapper else cmd
            proc = subprocess.Popen([str(self.interpreter("runsv")), "-I", "-S", str(FIXTURES / "runsv_double.py"),
                                     str(service), *program], env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        self.procs.append(proc)
        doc = _wait(lambda: ready.exists() and self.pid_file(service) and json.loads(ready.read_text()), 20)
        if not doc:
            raise AssertionError("target did not become ready")
        self.pids += [doc["pid"], *doc["children"]]
        return service, doc

    def spawn(self, mode, *, exe_name="ollama"):
        """A target that is NOT supervised (parent = this test process)."""
        ready = self.tmp / f"ready-{uuid.uuid4().hex}.json"
        proc = subprocess.Popen([str(self.interpreter(exe_name)), "-I", "-S", str(FIXTURES / "target.py"), mode,
                                 str(ready)], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(proc)
        doc = _wait(lambda: ready.exists() and json.loads(ready.read_text()), 20)
        self.pids += [doc["pid"], *doc["children"]]
        return doc

    @staticmethod
    def pid_file(service):
        try:
            return (service / "supervise" / "pid").read_text().strip()
        except OSError:
            return ""

    def anchor(self, name="ollama", sha=None):
        digest = sha or hashlib.sha256((self.bin / name).read_bytes()).hexdigest()
        return [{"name": name, "version": "test", "sha256": digest, "source": "hg-test-interpreter-copy",
                 "provenance": {"kind": "test fixture, never a production anchor"}}]

    def cleanup(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(5)
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)


def _layer(att, name):
    return att.layers[name]["status"], att.layers[name]["code"]


# ====================================================================== unit

class ParserTests(unittest.TestCase):
    def test_stat_comm_with_parentheses_spaces_and_newline(self):
        raw = b"4242 (a) b (c)\nd) S 17 4242 4242 0 -1 4194560 1 0 0 0 0 0 0 0 20 0 1 0 987654 1000 10\n"
        st = at.parse_stat(raw, 4242)
        self.assertEqual((st.pid, st.comm, st.state, st.ppid, st.starttime), (4242, "a) b (c)\nd", "S", 17, 987654))

    def test_stat_malformed_or_other_pid(self):
        for raw in (b"", b"12 noparen S 1", b"12 (x) S 1 2 3", b"12 (x"):
            with self.assertRaises(ValueError):
                at.parse_stat(raw, 12)
        good = b"12 (x) S 1 " + b"0 " * 17 + b"555 0 0\n"
        self.assertEqual(at.parse_stat(good, 12).starttime, 555)
        with self.assertRaises(ValueError):
            at.parse_stat(good, 13)

    @unittest.skipUnless(LINUX, "Linux /proc required")
    def test_real_self_stat(self):
        st = at.read_stat(os.getpid())
        self.assertEqual((st.pid, st.ppid), (os.getpid(), os.getppid()))
        self.assertGreater(st.starttime, 0)


class CredentialPolicyTests(unittest.TestCase):
    MINE = {"Uid": "1000\t1000\t1000\t1000", "Gid": "1000\t1000\t1000\t1000", "Groups": "3003 9997 1000",
            "CapInh": "0000000000000000", "CapPrm": "0000000000000000", "CapEff": "0000000000000000",
            "CapBnd": "000001ffffffffff", "CapAmb": "0000000000000000", "NoNewPrivs": "0", "Seccomp": "2"}

    def check(self, change=None, *, mine=None, ctx=("u:r:untrusted_app_27:s0:c1,c2", "u:r:untrusted_app_27:s0:c1,c2")):
        theirs = dict(self.MINE, **(change or {}))
        return at.check_credentials(mine or self.MINE, theirs, my_context=ctx[0], their_context=ctx[1])

    def test_identical_credentials_pass(self):
        self.assertEqual(self.check()["status"], "PASS")
        self.assertEqual(self.check({"Groups": "1000 3003 9997"})["status"], "PASS")   # order is irrelevant
        self.assertEqual(self.check({"NoNewPrivs": "1"})["status"], "PASS")           # stricter is fine

    def test_each_uid_and_gid_position(self):
        for pos in range(4):
            uids = ["1000"] * 4
            uids[pos] = "0"
            self.assertEqual(self.check({"Uid": " ".join(uids)})["code"], "UID_MISMATCH")
            self.assertEqual(self.check({"Gid": " ".join(uids)})["code"], "GID_MISMATCH")

    def test_supplementary_groups(self):
        self.assertEqual(self.check({"Groups": "3003 9997 1000 1015"})["code"], "GROUPS_MISMATCH")
        self.assertEqual(self.check({"Groups": "3003 1000"})["code"], "GROUPS_MISMATCH")

    def test_capabilities_beyond_own_sets(self):
        for key in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
            result = self.check({key: "0000000000200000"})
            self.assertEqual((result["code"], result["set"]), ("CAPABILITY_EXCEEDS_POLICY", key))
        self.assertEqual(self.check({"CapBnd": "000003ffffffffff"})["code"], "CAPABILITY_EXCEEDS_POLICY")
        self.assertEqual(self.check({"CapBnd": "0000000000000000"})["status"], "PASS")

    def test_seccomp_nnp_selinux(self):
        self.assertEqual(self.check({"Seccomp": "0"})["code"], "SECCOMP_MISMATCH")
        mine = dict(self.MINE, NoNewPrivs="1")
        self.assertEqual(self.check(mine=mine)["code"], "NO_NEW_PRIVS_DROPPED")
        self.assertEqual(self.check(ctx=("u:r:untrusted_app_27:s0:c1,c2", "u:r:shell:s0"))["code"],
                         "SELINUX_CONTEXT_MISMATCH")
        self.assertEqual(self.check(ctx=("u:r:untrusted_app_27:s0:c1,c2", None))["code"], "SELINUX_CONTEXT_UNREADABLE")
        self.assertEqual(self.check(ctx=(None, None))["selinux"], "NOT_APPLICABLE")

    def test_incomplete_status_fails_closed(self):
        for key in ("Uid", "Groups", "CapAmb", "Seccomp", "NoNewPrivs"):
            theirs = dict(self.MINE)
            del theirs[key]
            self.assertEqual(at.check_credentials(self.MINE, theirs)["code"], "STATUS_INCOMPLETE")
        self.assertEqual(self.check({"Uid": "1000 1000"})["code"], "STATUS_INCOMPLETE")


class TrustAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-anchor-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.entry = {"name": "ollama", "version": "0.40.13", "sha256": "a" * 64, "source": "termux-main",
                      "provenance": {"deb_sha256": "b" * 64}}

    def write(self, doc, name="anchor.json"):
        path = self.tmp / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_shipped_anchor_is_valid_and_empty(self):
        self.assertEqual(at.load_trust_anchor(), [])
        self.assertEqual(at._integrity("ollama", "a" * 64, [])["code"], "NO_TRUST_ANCHOR")

    def test_valid_entry_and_digest_decisions(self):
        entries = at.load_trust_anchor(self.write({"schema": at.ANCHOR_SCHEMA, "runtimes": [self.entry]}))
        self.assertEqual(at._integrity("ollama", "a" * 64, entries)["status"], "PASS")
        self.assertEqual(at._integrity("ollama", "c" * 64, entries)["code"], "DIGEST_NOT_ANCHORED")

    def test_malformed_anchors_rejected(self):
        bad = [{"schema": "other", "runtimes": []}, {"schema": at.ANCHOR_SCHEMA, "runtimes": {}},
               {"schema": at.ANCHOR_SCHEMA, "runtimes": [dict(self.entry, extra=1)]},
               {"schema": at.ANCHOR_SCHEMA, "runtimes": [dict(self.entry, sha256="A" * 64)]},
               {"schema": at.ANCHOR_SCHEMA, "runtimes": [dict(self.entry, provenance={})]}, []]
        for doc in bad:
            with self.assertRaises(at.AnchorError):
                at.load_trust_anchor(self.write(doc))
        good = self.write({"schema": at.ANCHOR_SCHEMA, "runtimes": [self.entry]})
        link = self.tmp / "link.json"
        link.symlink_to(good)
        with self.assertRaises(at.AnchorError):
            at.load_trust_anchor(link)
        with self.assertRaises(at.AnchorError):
            at.load_trust_anchor(self.tmp / "missing.json")


class CapabilityTests(unittest.TestCase):
    def fake(self, returncode, out=b""):
        return lambda *a, **k: subprocess.CompletedProcess(a, returncode, out, b"")

    def test_capability_outcomes(self):
        cases = [(0, b"0\n", "PASS", "AVAILABLE"), (-31, b"", "BLOCKED", "SECCOMP_SIGSYS"),
                 (3, b"38\n", "BLOCKED", "PIDFD_GETFD_ENOSYS"), (3, b"1\n", "BLOCKED", "PIDFD_GETFD_EPERM"),
                 (4, b"38\n", "BLOCKED", "PIDFD_OPEN_ENOSYS"), (9, b"x", "BLOCKED", "CAPABILITY_PROBE_FAILED")]
        try:
            for code, out, status, name in cases:
                result = at.capability(refresh=True, runner=self.fake(code, out))
                self.assertEqual((result["status"], result["code"]), (status, name))
        finally:
            at.capability(refresh=True)

    def test_overall_status_precedence(self):
        att = at.Attestation("/x", "127.0.0.1", 1, "/proc", None, "ollama")
        self.assertEqual(att.status, "UNVERIFIED")
        for layer in at.LAYERS:
            att.layers[layer] = at._result("PASS", "ok")
        self.assertEqual(att.status, "VERIFIED_LISTENER")
        att.layers["L3_integrity"] = at._result("UNVERIFIED", "NO_TRUST_ANCHOR")
        self.assertEqual(att.status, "UNVERIFIED")
        att.layers["L5_listener"] = at._result("BLOCKED", "PIDFD_GETFD_EPERM")
        self.assertEqual(att.status, "BLOCKED")
        att.layers["L4_credentials"] = at._result("FAIL", "UID_MISMATCH")
        self.assertEqual(att.status, "FAIL")
        self.assertEqual(att.reverify()["code"], "NOT_VERIFIED")


@unittest.skipUnless(LINUX, "Linux /proc required")
class PidFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-pidfile-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.service = self.tmp / "svc"
        (self.service / "supervise").mkdir(parents=True, mode=0o700)
        os.chmod(self.service, 0o700)
        self.pid = self.service / "supervise" / "pid"

    def code(self, service=None):
        with self.assertRaises(at._LayerFail) as caught:
            at.read_supervised_pid(str(service or self.service))
        return caught.exception.code

    def test_empty_missing_malformed(self):
        self.assertEqual(self.code(), "PID_FILE_UNUSABLE")
        self.pid.write_text("")
        self.assertEqual(self.code(), "PID_FILE_EMPTY")
        for text in ("abc", "0", "-1", "12 34", "12\n\n", "99999999", " 12", "0012"):
            self.pid.write_text(text)
            self.assertEqual(self.code(), "PID_FILE_MALFORMED", text)
        self.pid.write_text("4242\n")
        self.assertEqual(at.read_supervised_pid(str(self.service))[0], 4242)

    def test_not_regular_symlink_and_modes(self):
        os.mkfifo(self.pid)
        self.assertEqual(self.code(), "PID_FILE_NOT_REGULAR")
        self.pid.unlink()
        self.pid.mkdir()
        self.assertEqual(self.code(), "PID_FILE_NOT_REGULAR")
        self.pid.rmdir()
        real = self.tmp / "elsewhere"
        real.write_text("4242\n")
        self.pid.symlink_to(real)
        self.assertEqual(self.code(), "PID_FILE_SYMLINK")
        self.pid.unlink()
        self.pid.write_text("4242\n")
        os.chmod(self.pid, 0o664)
        self.assertEqual(self.code(), "PID_FILE_OWNER_OR_MODE")
        os.chmod(self.pid, 0o644)
        os.chmod(self.service, 0o777)
        self.assertEqual(self.code(), "SERVICE_DIR_OWNER_OR_MODE")
        os.chmod(self.service, 0o700)
        link = self.tmp / "svc-link"
        link.symlink_to(self.service)
        self.assertEqual(self.code(link), "SERVICE_DIR_UNUSABLE")


# ====================================================================== integration (real kernel)

class _LabCase(unittest.TestCase):
    def setUp(self):
        self.lab = Lab(self)
        cap = at.capability()
        if cap["status"] != "PASS":
            _skip(f"pidfd_getfd unavailable here: {cap['code']}")

    def attest(self, service, port, **kw):
        if "anchors" not in kw:
            kw["anchors"] = self.lab.anchor()
        att = at.attest(service, port=port, **kw)
        self.addCleanup(att.close)
        return att


class AttestHappyPathTests(_LabCase):
    def test_verified_listener_and_reverify(self):
        service, doc = self.lab.start("listen")
        att = self.attest(service, doc["port"])
        self.assertEqual(att.status, "VERIFIED_LISTENER", att.report())
        self.assertTrue(all(layer["status"] == "PASS" for layer in att.layers.values()))
        self.assertEqual(att.pid, doc["pid"])
        self.assertEqual(att.layers["L5_listener"]["fd"], doc["fd"])
        # an HTTP-like exchange happens here in production; the listener is still the same one
        with socket.create_connection(("127.0.0.1", doc["port"]), timeout=5):
            pass
        self.assertEqual(att.reverify()["status"], "PASS")
        json.dumps(att.report())                                   # report is JSON-serialisable

    def test_shipped_empty_anchor_keeps_overall_unverified_but_collects_l5(self):
        service, doc = self.lab.start("listen")
        att = self.attest(service, doc["port"], anchors=None)
        self.assertEqual(att.status, "UNVERIFIED")
        self.assertEqual(_layer(att, "L3_integrity"), ("UNVERIFIED", "NO_TRUST_ANCHOR"))
        self.assertEqual(_layer(att, "L5_listener"), ("PASS", "LISTENER_OWNED"))
        self.assertEqual(att.reverify()["code"], "NOT_VERIFIED")

    def cli(self, service, port):
        """The CLI runs as a sibling of the target (not its ancestor), as `hg` does on the phone."""
        repo = Path(__file__).resolve().parents[2]
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, "-B", "-m", "hg.assistant.attest", "--service-dir", str(service),
                               "--port", str(port)], cwd=repo, env=env, capture_output=True, timeout=60, check=False)
        self.assertTrue(done.stdout, done.stderr.decode("utf-8", "replace")[-400:])
        return done.returncode, json.loads(done.stdout)

    def test_cli_reports_json_and_exit_code(self):
        service, doc = self.lab.start("listen", ptracer_any=True)
        code, report = self.cli(service, doc["port"])
        self.assertEqual(code, 1)                                  # shipped anchor is empty -> not verified
        self.assertEqual(report["layers"]["L5_listener"]["status"], "PASS", report["layers"]["L5_listener"])
        self.assertEqual(report["capability"]["code"], "AVAILABLE")

    def test_cli_non_ancestor_under_yama_is_blocked_not_passed(self):
        if yama_scope() != 1:
            self.skipTest("Yama ptrace_scope is not 1 here: a non-ancestor attester is not restricted")
        service, doc = self.lab.start("listen")                    # no PR_SET_PTRACER exception
        code, report = self.cli(service, doc["port"])
        self.assertEqual(code, 1)
        self.assertEqual((report["layers"]["L5_listener"]["status"], report["layers"]["L5_listener"]["code"]),
                         ("BLOCKED", "PIDFD_GETFD_EPERM"))
        self.assertEqual(report["status"], "BLOCKED")


class AttestL1Tests(_LabCase):
    def test_parent_is_not_runsv(self):
        doc = self.lab.spawn("listen")
        service = self.lab.service()
        (service / "supervise").mkdir(mode=0o700)
        (service / "supervise" / "pid").write_text(f"{doc['pid']}\n")
        att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L1_supervision"), ("FAIL", "PARENT_NOT_RUNSV"))
        self.assertEqual(att.status, "FAIL")

    def test_runsv_of_another_service(self):
        other, doc = self.lab.start("listen")
        service = self.lab.service()
        (service / "supervise").mkdir(mode=0o700)
        (service / "supervise" / "pid").write_text(f"{doc['pid']}\n")
        att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L1_supervision"), ("FAIL", "RUNSV_OF_ANOTHER_SERVICE"))

    def test_stale_pid(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        service = self.lab.service()
        (service / "supervise").mkdir(mode=0o700)
        (service / "supervise" / "pid").write_text(f"{dead.pid}\n")
        att = self.attest(service, 1)
        self.assertEqual(_layer(att, "L1_supervision"), ("FAIL", "STALE_PID"))

    def test_pid_reuse_between_reads_is_detected(self):
        service, doc = self.lab.start("listen")
        real, calls = at.read_stat, []

        def flaky(pid, *, proc="/proc"):
            st = real(pid, proc=proc)
            calls.append(pid)
            if pid == doc["pid"] and len([c for c in calls if c == doc["pid"]]) == 2:
                st.starttime += 1                                # what a recycled PID would look like
            return st

        with mock.patch.object(at, "read_stat", flaky):
            att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L1_supervision"), ("FAIL", "PID_REUSED_OR_EXITED"))

    def test_shell_wrapper_run_script(self):
        service, doc = self.lab.start("listen", wrapper=True)
        att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L1_supervision")[0], "PASS")   # sh is runsv's child...
        self.assertEqual(_layer(att, "L2_identity"), ("FAIL", "EXE_NAME_MISMATCH"))   # ...but not ollama
        self.assertNotEqual(att.pid, doc["pid"])


class AttestL2L3Tests(_LabCase):
    def test_wrong_executable_name(self):
        service, doc = self.lab.start("listen", exe_name="python-other")
        att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L2_identity"), ("FAIL", "EXE_NAME_MISMATCH"))

    def test_same_name_wrong_digest(self):
        service, doc = self.lab.start("listen")
        att = self.attest(service, doc["port"], anchors=self.lab.anchor(sha="0" * 64))
        self.assertEqual(_layer(att, "L3_integrity"), ("FAIL", "DIGEST_NOT_ANCHORED"))
        self.assertEqual(att.status, "FAIL")

    def test_execve_during_attestation(self):
        service, doc = self.lab.start("listen", usr1="exec")
        pid = doc["pid"]
        before = os.stat(f"/proc/{pid}/exe").st_ino

        def exec_now(_pid):
            os.kill(pid, signal.SIGUSR1)
            _wait(lambda: os.stat(f"/proc/{pid}/exe").st_ino != before, 5)

        att = self.attest(service, doc["port"], _hooks=at._Hooks(after_hash=exec_now))
        self.assertEqual(_layer(att, "L2_identity"), ("FAIL", "EXEC_DURING_ATTESTATION"))

    def test_process_killed_during_attestation(self):
        service, doc = self.lab.start("listen")

        def kill_now(_pid):
            os.kill(doc["pid"], signal.SIGKILL)
            _wait(lambda: not os.path.exists(f"/proc/{doc['pid']}/exe") or
                  at.read_stat(doc["pid"]).state in ("Z", "X"), 5)

        att = self.attest(service, doc["port"], _hooks=at._Hooks(after_hash=kill_now))
        self.assertEqual(_layer(att, "L2_identity")[0], "FAIL")
        self.assertIn(att.layers["L2_identity"]["code"], ("PROCESS_EXITED", "PID_REUSED_OR_EXITED"))

    def test_executable_metadata_changed_during_hash(self):
        service, doc = self.lab.start("listen")
        exe = self.lab.bin / "ollama"

        def touch(_pid):
            os.chmod(exe, 0o750)                      # changes ctime of the running image's inode
            os.chmod(exe, 0o755)

        att = self.attest(service, doc["port"], _hooks=at._Hooks(after_hash=touch))
        self.assertEqual(_layer(att, "L2_identity"), ("FAIL", "EXE_CHANGED_DURING_HASH"))

    def test_unreadable_executable_fails_closed(self):
        service, doc = self.lab.start("listen")
        real_open = os.open

        def guarded(path, flags, *args, **kwargs):
            if str(path) == f"/proc/{doc['pid']}/exe":
                raise PermissionError(errno.EACCES, "denied")
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(at.os, "open", guarded):
            att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L2_identity"), ("FAIL", "EXE_UNREADABLE"))
        self.assertEqual(att.status, "FAIL")

    def test_deleted_executable(self):
        service, doc = self.lab.start("listen")
        (self.lab.bin / "ollama").unlink()
        att = self.attest(service, doc["port"], anchors=[])
        self.assertEqual(_layer(att, "L2_identity"), ("FAIL", "EXE_DELETED"))


class AttestL4Tests(_LabCase):
    def test_same_user_target_passes_real_status(self):
        service, doc = self.lab.start("listen")
        att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L4_credentials"), ("PASS", "CREDENTIALS_MATCH_POLICY"))

    def test_unreadable_status_fails_closed(self):
        service, doc = self.lab.start("listen")
        real = at.read_status

        def denied(pid, *, proc="/proc"):
            if pid != "self":
                raise PermissionError(errno.EACCES, "denied")
            return real(pid, proc=proc)

        with mock.patch.object(at, "read_status", denied):
            att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L4_credentials"), ("FAIL", "STATUS_UNREADABLE"))
        self.assertEqual(att.status, "FAIL")


class AttestL5Tests(_LabCase):
    def l5(self, mode, **kw):
        service, doc = self.lab.start(mode, **{k: v for k, v in kw.items() if k in ("usr1",)})
        att = self.attest(service, kw.get("port", doc["port"]), **{k: v for k, v in kw.items()
                                                                  if k not in ("usr1", "port")})
        return att, doc

    def test_not_listening_udp_wrong_port(self):
        for mode in ("bound", "udp"):
            att, _ = self.l5(mode)
            self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "NO_LISTENER"), mode)
        service, doc = self.lab.start("listen")
        att = self.attest(service, doc["port"] + 1 if doc["port"] < 65535 else doc["port"] - 1)
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "NO_LISTENER"))

    def test_wrong_bind_address(self):
        att, _ = self.l5("wildcard")
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "UNEXPECTED_BIND_ON_PORT"))
        att, _ = self.l5("two-loopback")
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "UNEXPECTED_BIND_ON_PORT"))

    def test_reuseport_single_and_double(self):
        att, _ = self.l5("reuseport1")
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "REUSEPORT_SET"))
        att, _ = self.l5("reuseport2")
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "MULTIPLE_LISTENERS"))

    def test_listener_shared_with_another_process(self):
        att, doc = self.l5("shared")
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "LISTENER_SHARED"))
        self.assertIn(doc["children"][0], att.layers["L5_listener"]["holders"])

    def test_api_answers_but_another_process_owns_the_port_F1(self):
        """F-1: the old check calls this VERIFIED_PROCESS; L5 finds no listener in the attested process."""
        service, doc = self.lab.start("none")
        impostor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(impostor.close)
        impostor.bind(("127.0.0.1", 0))
        impostor.listen(4)
        port = impostor.getsockname()[1]
        legacy = cfg.attest_listener(dict(cfg.DEFAULTS, ollama_service_dir=str(service)))
        self.assertEqual((legacy["status"], legacy["listener"]), ("VERIFIED_PROCESS", "UNVERIFIED"))
        att = self.attest(service, port)
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "NO_LISTENER"))
        self.assertEqual(att.status, "FAIL")

    def test_descriptor_closed_and_reused_between_listing_and_getfd(self):
        service, doc = self.lab.start("listen", usr1="reuse")
        listener_fd, pid = doc["fd"], doc["pid"]
        before = os.readlink(f"/proc/{pid}/fd/{listener_fd}")

        def swap(number):
            if number == listener_fd:
                os.kill(pid, signal.SIGUSR1)
                _wait(lambda: os.readlink(f"/proc/{pid}/fd/{listener_fd}") != before, 5)

        att = self.attest(service, doc["port"], _hooks=at._Hooks(before_getfd=swap))
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "NO_LISTENER"))
        self.assertGreaterEqual(att.layers["L5_listener"]["raced"], 1)

    def test_pidfd_getfd_errors(self):
        service, doc = self.lab.start("listen")
        for err, status, code in ((errno.EPERM, "BLOCKED", "PIDFD_GETFD_EPERM"),
                                  (errno.EACCES, "BLOCKED", "PIDFD_GETFD_EACCES"),
                                  (errno.ENOSYS, "BLOCKED", "PIDFD_GETFD_ENOSYS"),
                                  (errno.ESRCH, "FAIL", "PROCESS_EXITED"),
                                  (errno.EBADF, "FAIL", "NO_LISTENER")):
            def getfd(_pidfd, _fd, err=err):
                raise OSError(err, os.strerror(err))
            att = self.attest(service, doc["port"], getfd=getfd)
            self.assertEqual(_layer(att, "L5_listener"), (status, code))
            self.assertNotEqual(att.status, "VERIFIED_LISTENER")

    def test_seccomp_or_missing_syscall_blocks_l5(self):
        service, doc = self.lab.start("listen")
        with mock.patch.object(at, "capability", lambda: at._result("BLOCKED", "SECCOMP_SIGSYS")):
            att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L5_listener"), ("BLOCKED", "SECCOMP_SIGSYS"))
        self.assertEqual(att.status, "BLOCKED")

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which("unshare"), "needs root and unshare(1)")
    def test_other_network_namespace(self):
        service = self.lab.service()
        ready = self.lab.tmp / "ready-ns.json"
        cmd = [shutil.which("unshare"), "-n", str(self.lab.interpreter("ollama")), "-I", "-S",
               str(FIXTURES / "target.py"), "listen", str(ready)]
        proc = subprocess.Popen([str(self.lab.interpreter("runsv")), "-I", "-S", str(FIXTURES / "runsv_double.py"),
                                 str(service), *cmd], env=self.lab.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.lab.procs.append(proc)
        doc = _wait(lambda: ready.exists() and json.loads(ready.read_text()), 20)
        if not doc:
            self.skipTest("unshare -n not permitted here")
        self.lab.pids.append(doc["pid"])
        att = self.attest(service, doc["port"])
        self.assertEqual(_layer(att, "L5_listener"), ("FAIL", "NETNS_MISMATCH"))


class AttestBracketTests(_LabCase):
    def verified(self, usr1=""):
        service, doc = self.lab.start("listen", usr1=usr1)
        att = self.attest(service, doc["port"])
        self.assertEqual(att.status, "VERIFIED_LISTENER", att.report())
        return att, doc

    def test_listener_closed_after_attestation(self):
        att, doc = self.verified(usr1="close")
        os.kill(doc["pid"], signal.SIGUSR1)
        self.assertTrue(_wait(lambda: not os.path.exists(f"/proc/{doc['pid']}/fd/{doc['fd']}"), 5))
        self.assertEqual(att.reverify()["code"], "LISTENER_GONE")

    def test_listener_replaced_after_attestation(self):
        att, doc = self.verified(usr1="reuse")
        before = os.readlink(f"/proc/{doc['pid']}/fd/{doc['fd']}")
        os.kill(doc["pid"], signal.SIGUSR1)
        _wait(lambda: os.readlink(f"/proc/{doc['pid']}/fd/{doc['fd']}") != before, 5)
        self.assertEqual(att.reverify()["code"], "LISTENER_REPLACED")

    def test_service_restart_after_attestation(self):
        att, doc = self.verified()
        os.kill(doc["pid"], signal.SIGKILL)
        _wait(lambda: Lab.pid_file(Path(att.service_dir)) not in ("", str(doc["pid"])), 10)
        self.assertIn(att.reverify()["code"], ("SERVICE_RESTARTED", "PROCESS_EXITED"))

    def test_exec_after_attestation(self):
        att, doc = self.verified(usr1="exec")
        before = os.stat(f"/proc/{doc['pid']}/exe").st_ino
        os.kill(doc["pid"], signal.SIGUSR1)
        _wait(lambda: os.stat(f"/proc/{doc['pid']}/exe").st_ino != before, 5)
        self.assertEqual(att.reverify()["code"], "EXEC_SINCE_ATTESTATION")


@unittest.skipUnless(LINUX, "Linux required")
class KernelBindSemanticsTests(unittest.TestCase):
    """The L5 uniqueness argument: while a LISTEN socket without SO_REUSEPORT holds 127.0.0.1:P, no other
    socket can bind 127.0.0.1:P or 0.0.0.0:P, even with SO_REUSEADDR or SO_REUSEPORT of its own."""

    def test_exclusive_bind_while_listening(self):
        first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(first.close)
        first.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        first.bind(("127.0.0.1", 0))
        first.listen(4)
        port = first.getsockname()[1]
        for addr, reuseport in (("127.0.0.1", False), ("0.0.0.0", False), ("127.0.0.1", True), ("0.0.0.0", True)):
            other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if reuseport:
                other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            with self.assertRaises(OSError) as caught:
                other.bind((addr, port))
            other.close()
            self.assertEqual(caught.exception.errno, errno.EADDRINUSE, (addr, reuseport))


@unittest.skipUnless(SUPERVISOR == "runit" or REQUIRE, "real runit not installed (stand-in covers the rest)")
class RealRunitTests(_LabCase):
    def test_real_runsv_supervised_listener(self):
        service, doc = self.lab.start("listen", supervisor="runit")
        att = self.attest(service, doc["port"])
        self.assertEqual(att.status, "VERIFIED_LISTENER", att.report())
        self.assertEqual(at.read_stat(att.layers["L1_supervision"]["runsv_pid"]).comm, "runsv")


if __name__ == "__main__":
    unittest.main()
