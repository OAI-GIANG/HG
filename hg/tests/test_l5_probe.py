"""The standalone L5 probe (deploy/termux/l5_probe.py), run as a separate process on the real kernel.

It must stay independent of HG (no `hg` import) so it can run on the phone from any checkout."""
import ast
import errno
import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from hg.assistant import attest as at
from hg.tests.test_attest import yama_scope

PROBE = Path(__file__).resolve().parents[2] / "deploy" / "termux" / "l5_probe.py"
PROBE_SPEC = importlib.util.spec_from_file_location("hg_l5_probe_standalone", PROBE)
PROBE_MODULE = importlib.util.module_from_spec(PROBE_SPEC)
PROBE_SPEC.loader.exec_module(PROBE_MODULE)
REQUIRE = os.environ.get("HG_REQUIRE_PROC_TESTS") == "1"
PROC_PLATFORM = sys.platform in ("linux", "android") and os.path.isdir("/proc/self/fd")


def run_probe(*args, timeout=90):
    done = subprocess.run([sys.executable, "-I", "-S", str(PROBE), *args], capture_output=True, timeout=timeout,
                          check=False)
    return done.returncode, (json.loads(done.stdout) if done.stdout.strip().startswith(b"{") else None), done


def env_unmet(reason):
    """The single place where a missing environment capability ends a test. With HG_REQUIRE_PROC_TESTS=1 it is a
    FAILURE (a required L5 capability is absent), never a skip; otherwise it is an explicit SKIP with the reason.
    It is for environment limits only: a logic or execution error must fail the test, not call this."""
    if REQUIRE:
        raise AssertionError(f"HG_REQUIRE_PROC_TESTS=1 but a required L5 capability is missing: {reason}")
    raise unittest.SkipTest(reason)


BLOCKING_CODES = {
    "FD_TABLE_EPERM", "FD_TABLE_EACCES",
    "PIDFD_GETFD_EPERM", "PIDFD_GETFD_EACCES", "PIDFD_GETFD_ENOSYS",
    "SHARING_SCAN_INCOMPLETE", "SELF_TEST_OBSERVATION_INCOMPLETE",
}


def process_observation_limited(report):
    """True only when the runner explicitly prevents complete cross-process observation: a permission-denied
    syscall, an uninspectable process of any UID class, an unreadable descriptor, a restricted or unknown
    hidepid, or a scan that declares itself PARTIAL."""
    if not isinstance(report, dict):
        return False
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    code = result.get("code", "")
    if code in BLOCKING_CODES:
        return True
    errors = report.get("errors")
    if isinstance(errors, list) and errors and all(
        isinstance(error, dict)
        and error.get("stage") == "pidfd_getfd"
        and error.get("errno") in {"EPERM", "EACCES", "ENOSYS"}
        for error in errors
    ):
        return True
    sharing = report.get("sharing")
    if not isinstance(sharing, dict):
        return False
    uninspectable = sharing.get("uninspectable")
    if not isinstance(uninspectable, dict):
        return False
    return bool(
        any(uninspectable.get(key, 0) for key in ("same_uid", "root", "other_uid", "unknown"))
        or sharing.get("unreadable_descriptors", 0)
        or sharing.get("proc_hidepid") not in (None, "0", "off")
        or sharing.get("scope", "ALL_PROCESSES_INSPECTED") != "ALL_PROCESSES_INSPECTED"
    )


class ProbeIndependenceTests(unittest.TestCase):
    def test_probe_imports_only_the_standard_library(self):
        tree = ast.parse(PROBE.read_text(encoding="utf-8"))
        names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}
        names |= {node.module.split(".")[0] for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom) and node.module}
        self.assertNotIn("hg", names)
        self.assertNotIn("maep", names)
        self.assertTrue(names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names))

    def test_usage_error(self):
        code, report, _ = run_probe("--bogus")
        self.assertEqual((code, report), (3, None))




class ProbeDecisionTests(unittest.TestCase):
    def row(self, proto=socket.IPPROTO_TCP):
        return {"fd": 5, "inode_listed": 555, "inode_dup": 555, "consistent": True,
                "family": "AF_INET", "type": "SOCK_STREAM", "proto": proto,
                "listening": True, "reuseport": False, "address": "127.0.0.1", "port": 11434}

    @staticmethod
    def sharing(scope="ALL_PROCESSES_INSPECTED", hidepid=None, unreadable=0, scan_errors=None, **uninspectable):
        counters = {"same_uid": 0, "root": 0, "other_uid": 0, "unknown": 0}
        counters.update(uninspectable)
        return {"uninspectable": counters, "unreadable_descriptors": unreadable, "proc_hidepid": hidepid,
                "scan_errors": scan_errors or [], "scope": scope}

    def run_target(self, row=None, errors=None, sharing=None, found=None, rows=None, starttimes=None,
                   inspects=None, exited=False, expect="127.0.0.1:11434"):
        rows = [self.row()] if rows is None and row is None else ([row] if rows is None else rows)
        errors = [] if errors is None else errors
        sharing = self.sharing() if sharing is None else sharing
        starttime = ({"return_value": 77} if starttimes is None else {"side_effect": starttimes})
        inspect = ({"return_value": (rows, errors)} if inspects is None else {"side_effect": inspects})
        report = {}
        with mock.patch.object(PROBE_MODULE.os, "readlink", return_value="/usr/bin/ollama"), \
             mock.patch.object(PROBE_MODULE, "status_fields", return_value={}), \
             mock.patch.object(PROBE_MODULE, "starttime", **starttime), \
             mock.patch.object(PROBE_MODULE, "pidfd_open", return_value=999), \
             mock.patch.object(PROBE_MODULE.os, "close"), \
             mock.patch.object(PROBE_MODULE, "inspect", **inspect), \
             mock.patch.object(PROBE_MODULE, "exited", return_value=exited), \
             mock.patch.object(PROBE_MODULE, "holders", return_value=([] if found is None else found, sharing)):
            code = PROBE_MODULE.target(report, 123, expect)
        return code, report

    def test_platform_gate_accepts_android_and_linux_only(self):
        self.assertTrue(PROBE_MODULE.supported_platform("android"))
        self.assertTrue(PROBE_MODULE.supported_platform("linux"))
        self.assertFalse(PROBE_MODULE.supported_platform("darwin"))

    def test_process_observation_gate_recognizes_explicit_permission_denial(self):
        report = {"errors": [{"fd": 7, "stage": "pidfd_getfd", "errno": "EPERM"}]}
        self.assertTrue(process_observation_limited(report))

    def test_process_observation_gate_recognizes_unknown_proc_visibility(self):
        report = {"sharing": {
            "uninspectable": {"same_uid": 0, "root": 0, "other_uid": 0, "unknown": 1},
            "unreadable_descriptors": 0, "proc_hidepid": None,
        }}
        self.assertTrue(process_observation_limited(report))

    def test_process_observation_gate_does_not_hide_unrelated_probe_errors(self):
        report = {"errors": [{"fd": 8, "stage": "readlink", "errno": "EIO"}]}
        self.assertFalse(process_observation_limited(report))

    def test_target_blocks_partial_descriptor_inspection(self):
        code, report = self.run_target(errors=[{"fd": 8, "stage": "readlink", "errno": "EIO"}])
        self.assertEqual(code, 2)
        self.assertEqual(report["result"]["code"], "INSPECTION_INCOMPLETE")

    def test_target_requires_tcp_not_only_stream(self):
        sctp = getattr(socket, "IPPROTO_SCTP", 132)
        code, report = self.run_target(row=self.row(proto=sctp))
        self.assertEqual(code, 1)
        self.assertEqual(report["result"]["code"], "NO_UNIQUE_LISTENER")

    def test_holder_scan_marks_unexpected_oserror_partial(self):
        def listdir(path):
            if path == "/proc":
                return ["321"]
            if path == "/proc/321/fd":
                raise OSError(errno.EIO, "simulated fd-table read error")
            raise AssertionError(path)

        with mock.patch.object(PROBE_MODULE.os, "geteuid", return_value=1000), \
             mock.patch.object(PROBE_MODULE.os, "listdir", side_effect=listdir), \
             mock.patch.object(PROBE_MODULE.os.path, "exists", return_value=True), \
             mock.patch.object(PROBE_MODULE, "proc_hidepid", return_value=None):
            found, sharing = PROBE_MODULE.holders(555, set())
        self.assertEqual(found, [])
        self.assertEqual(sharing["scope"], "PARTIAL")
        self.assertEqual(sharing["uninspectable"]["unknown"], 1)

    def test_target_blocks_unknown_holder_scan(self):
        sharing = {"uninspectable": {"same_uid": 0, "root": 0, "other_uid": 0, "unknown": 1},
                   "unreadable_descriptors": 0, "proc_hidepid": None, "scope": "PARTIAL"}
        code, report = self.run_target(sharing=sharing)
        self.assertEqual(code, 2)
        self.assertEqual(report["result"]["code"], "SHARING_SCAN_INCOMPLETE")

    # ---- fail-closed decision table: an incomplete observation is never LISTENER_OWNED ------------------------

    def test_target_decision_table(self):
        S = self.sharing
        owned = (0, "PASS", "LISTENER_OWNED")
        blocked = (2, "BLOCKED", "SHARING_SCAN_INCOMPLETE")
        cases = [
            ("1 uninspectable same UID", dict(sharing=S(scope="PARTIAL", same_uid=1)), blocked),
            ("2 uninspectable root", dict(sharing=S(scope="PARTIAL", root=1)), blocked),
            ("3 uninspectable other UID", dict(sharing=S(scope="PARTIAL", other_uid=1)), blocked),
            ("4 uninspectable unknown UID", dict(sharing=S(scope="PARTIAL", unknown=1)), blocked),
            ("5 unreadable descriptors", dict(sharing=S(scope="PARTIAL", unreadable=2)), blocked),
            ("6 hidepid=1", dict(sharing=S(scope="PARTIAL", hidepid="1")), blocked),
            ("7 hidepid=2", dict(sharing=S(scope="PARTIAL", hidepid="2")), blocked),
            ("8 hidepid=UNKNOWN", dict(sharing=S(scope="PARTIAL", hidepid="UNKNOWN")), blocked),
            ("9 scope PARTIAL, every counter 0", dict(sharing=S(scope="PARTIAL")), blocked),
            ("9b counters 0 but scope missing", dict(sharing={k: v for k, v in S().items() if k != "scope"}), blocked),
            ("9c hidepid key missing", dict(sharing={k: v for k, v in S().items() if k != "proc_hidepid"}), blocked),
            ("9d counter not an integer", dict(sharing=S(root="0")), blocked),
            ("9e hidepid=noaccess", dict(sharing=S(hidepid="noaccess")), blocked),
            ("9f scan errors recorded", dict(sharing=S(scan_errors=[{"pid": 9, "stage": "list_fd"}])), blocked),
            ("10 full scan, no holder", dict(), owned),
            ("10b full scan, hidepid=0", dict(sharing=S(hidepid="0")), owned),
            ("11 other holder, full scan", dict(found=[4242]), (1, "FAIL", "LISTENER_SHARED")),
            ("11b other holder outranks an incomplete scan", dict(found=[4242], sharing=S(scope="PARTIAL", root=1)),
             (1, "FAIL", "LISTENER_SHARED")),
            ("13 listener on the wrong port", dict(row={**self.row(), "port": 11435}),
             (1, "FAIL", "NO_UNIQUE_LISTENER")),
            ("14a pid reused before the scan", dict(starttimes=[77, 78]), (1, "FAIL", "PID_REUSED_OR_EXITED")),
            ("14b pid reused after the scan", dict(starttimes=[77, 77, 77, 78]),
             (1, "FAIL", "PID_REUSED_OR_EXITED")),
            ("14c process exited", dict(exited=True), (1, "FAIL", "NO_UNIQUE_LISTENER")),
        ]
        for name, kwargs, (want_code, want_status, want_result) in cases:
            with self.subTest(name):
                code, report = self.run_target(**kwargs)
                self.assertEqual((code, report["result"]["status"], report["result"]["code"]),
                                 (want_code, want_status, want_result), report["result"])
                if code == 0:
                    self.assertEqual(report["sharing"]["scope"], "ALL_PROCESSES_INSPECTED")
                if report["result"]["code"] == "SHARING_SCAN_INCOMPLETE":
                    self.assertTrue(report["result"]["gaps"])

    def test_target_duplicate_descriptor_of_one_socket_is_one_listener(self):
        second = {**self.row(), "fd": 9}                       # same inode_dup: dup() of the same socket
        code, report = self.run_target(rows=[self.row(), second])
        self.assertEqual((code, report["result"]["code"], report["result"]["fds"]), (0, "LISTENER_OWNED", [5, 9]))

    def test_target_two_distinct_listeners_are_not_one_listener(self):
        other = {**self.row(), "fd": 9, "inode_listed": 556, "inode_dup": 556}
        code, report = self.run_target(rows=[self.row(), other])
        self.assertEqual((code, report["result"]["code"]), (1, "NO_UNIQUE_LISTENER"))

    def test_target_listener_swapped_during_scan_is_not_owned(self):
        swapped = {**self.row(), "inode_listed": 556, "inode_dup": 556}
        code, report = self.run_target(inspects=[([self.row()], []), ([swapped], [])])
        self.assertEqual((code, report["result"]["code"]), (1, "LISTENER_CHANGED"))

    def test_target_post_check_inspection_error_blocks(self):
        err = [{"fd": 5, "stage": "pidfd_getfd", "errno": "EPERM"}]
        code, report = self.run_target(inspects=[([self.row()], []), ([self.row()], err)])
        self.assertEqual((code, report["result"]["code"]), (2, "POST_CHECK_INCOMPLETE"))

    def test_holders_scope_follows_hidepid_and_counters(self):
        for hidepid, scope in [(None, "ALL_PROCESSES_INSPECTED"), ("0", "ALL_PROCESSES_INSPECTED"),
                               ("off", "ALL_PROCESSES_INSPECTED"), ("1", "PARTIAL"), ("2", "PARTIAL"),
                               ("noaccess", "PARTIAL"), ("invisible", "PARTIAL"), ("UNKNOWN", "PARTIAL")]:
            with self.subTest(hidepid=hidepid), \
                    mock.patch.object(PROBE_MODULE.os, "listdir", return_value=[]), \
                    mock.patch.object(PROBE_MODULE, "proc_hidepid", return_value=hidepid):
                found, sharing = PROBE_MODULE.holders(555, set())
            self.assertEqual((found, sharing["scope"]), ([], scope))

    def test_holders_marks_each_uid_class_of_unreadable_process_partial(self):
        for uid, key in [(1000, "same_uid"), (0, "root"), (2000, "other_uid"), (None, "unknown")]:
            def listdir(path, uid=uid):
                if path == "/proc":
                    return ["321"]
                raise PermissionError(errno.EACCES, "denied")
            status = {"Uid": f"{uid}\t{uid}\t{uid}\t{uid}"} if uid is not None else {}
            with self.subTest(key), mock.patch.object(PROBE_MODULE.os, "geteuid", return_value=1000), \
                    mock.patch.object(PROBE_MODULE.os, "listdir", side_effect=listdir), \
                    mock.patch.object(PROBE_MODULE, "status_fields", return_value=status), \
                    mock.patch.object(PROBE_MODULE, "proc_hidepid", return_value=None):
                found, sharing = PROBE_MODULE.holders(555, set())
            self.assertEqual((found, sharing["scope"], sharing["uninspectable"][key]), ([], "PARTIAL", 1))
            self.assertTrue(PROBE_MODULE.observation_gaps(sharing))

    def test_holders_marks_unreadable_descriptor_partial(self):
        def listdir(path):
            return ["321"] if path == "/proc" else ["3"]
        with mock.patch.object(PROBE_MODULE.os, "listdir", side_effect=listdir), \
                mock.patch.object(PROBE_MODULE.os, "readlink", side_effect=PermissionError(errno.EACCES, "x")), \
                mock.patch.object(PROBE_MODULE, "proc_hidepid", return_value=None):
            found, sharing = PROBE_MODULE.holders(555, set())
        self.assertEqual((found, sharing["scope"], sharing["unreadable_descriptors"]), ([], "PARTIAL", 1))

    def run_main(self, self_test_code, report_extra=None):
        import contextlib
        import io

        def fake_self_test(report):
            report.update(report_extra or {})
            return self_test_code

        out = io.StringIO()
        with mock.patch.object(PROBE_MODULE, "self_test", fake_self_test), \
                mock.patch.object(PROBE_MODULE, "supported_platform", return_value=True), \
                mock.patch.object(PROBE_MODULE, "environment", return_value={}), \
                mock.patch.object(PROBE_MODULE, "syscall_check", return_value={"status": "AVAILABLE"}), \
                contextlib.redirect_stdout(out):
            code = PROBE_MODULE.main([])
        return code, json.loads(out.getvalue())

    def test_self_test_with_incomplete_observation_is_blocked_not_pass(self):
        code, report = self.run_main(2, {"observation_gaps": ["SCOPE_PARTIAL"]})
        self.assertEqual(code, 2)
        self.assertEqual(report["result"], {"status": "BLOCKED", "code": "SELF_TEST_OBSERVATION_INCOMPLETE",
                                            "gaps": ["SCOPE_PARTIAL"]})
        self.assertEqual(self.run_main(1)[1]["result"], {"status": "FAIL", "code": "SELF_TEST"})
        self.assertEqual(self.run_main(0)[1]["result"], {"status": "PASS", "code": "SELF_TEST"})

    def test_self_test_verdict_never_passes_on_holder_or_gap(self):
        ok = {"a": True, "listener_not_shared": True}
        shared = {"a": True, "listener_not_shared": False}
        for name, checks, found, gaps, want in [
                ("all good", ok, [], [], 0),
                ("incomplete scan, no holder", shared, [], ["SCOPE_PARTIAL"], 2),
                ("holder found", shared, [7], [], 1),
                ("holder found and incomplete scan", shared, [7], ["UNINSPECTABLE_ROOT"], 1),
                ("another check also failed", {"a": False, "listener_not_shared": False}, [], ["SCOPE_PARTIAL"], 1),
                ("unrelated check failed", {"a": False, "listener_not_shared": True}, [], [], 1)]:
            with self.subTest(name):
                self.assertEqual(PROBE_MODULE.self_test_verdict(checks, found, gaps), want)

    def test_external_gate_variable_only_deselects_the_real_kernel_tests(self):
        module = sys.modules[__name__]

        def names(env):
            with mock.patch.dict(os.environ, env, clear=False):
                if "HG_L5_REAL_KERNEL_GATE" not in env:
                    os.environ.pop("HG_L5_REAL_KERNEL_GATE", None)
                suite = unittest.defaultTestLoader.loadTestsFromModule(module)
            return {type(test).__name__ for test in _flatten(suite)}, len(list(_flatten(suite)))

        default, default_count = names({})
        external, external_count = names({"HG_L5_REAL_KERNEL_GATE": "external"})
        self.assertIn("ProbeRunTests", default)
        self.assertNotIn("ProbeRunTests", external)
        self.assertLessEqual(external, default)
        self.assertEqual(default_count - external_count, 5)          # exactly the five real-kernel tests
        self.assertIn("ProbeDecisionTests", external)                 # the decision table always runs
        other, _ = names({"HG_L5_REAL_KERNEL_GATE": "anything-else"})
        self.assertIn("ProbeRunTests", other)                         # only the exact value deselects

    def test_missing_capability_follows_the_require_policy(self):
        """HG_REQUIRE_PROC_TESTS=1 turns any environment limit into a failure; otherwise it is an explicit skip."""
        with mock.patch(f"{__name__}.REQUIRE", True), self.assertRaises(AssertionError) as caught:
            env_unmet("pidfd_getfd unavailable: SECCOMP_SIGSYS")
        self.assertIn("HG_REQUIRE_PROC_TESTS=1", str(caught.exception))
        with mock.patch(f"{__name__}.REQUIRE", False), self.assertRaises(unittest.SkipTest) as caught:
            env_unmet("pidfd_getfd unavailable: SECCOMP_SIGSYS")
        self.assertIn("SECCOMP_SIGSYS", str(caught.exception))

    def test_every_skip_in_this_module_goes_through_env_unmet(self):
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = [node.lineno for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr in ("skipTest", "skip", "skipUnless", "skipIf")]
        decorators = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                      and node.attr in ("skipUnless", "skipIf", "skip")]
        self.assertEqual(sorted(set(offenders + decorators)), [], "use env_unmet() so REQUIRE mode cannot skip")

    def test_observation_limited_gate_covers_every_incomplete_case(self):
        S = self.sharing
        for name, sharing in [("same_uid", S(same_uid=1)), ("root", S(root=1)), ("other_uid", S(other_uid=1)),
                              ("unknown", S(unknown=1)), ("unreadable", S(unreadable=1)), ("hidepid1", S(hidepid="1")),
                              ("hidepid2", S(hidepid="2")), ("hidepidUNKNOWN", S(hidepid="UNKNOWN")),
                              ("partial", S(scope="PARTIAL"))]:
            with self.subTest(name):
                self.assertTrue(process_observation_limited({"sharing": sharing}))
        self.assertFalse(process_observation_limited({"sharing": S()}))
        self.assertFalse(process_observation_limited({"sharing": S(hidepid="0")}))


class ProbeRunTests(unittest.TestCase):
    def setUp(self):
        if not PROC_PLATFORM:
            env_unmet("Linux/Android /proc required")
        cap = at.capability()
        if cap["status"] != "PASS":
            env_unmet(f"pidfd_getfd unavailable: {cap['code']}")

    def test_self_test_passes_every_check(self):
        code, report, done = run_probe()
        if code != 0 and process_observation_limited(report):
            env_unmet("runner policy prevents complete cross-process /proc or pidfd_getfd observation: "
                      + json.dumps((report or {}).get("result"), sort_keys=True))
        self.assertEqual(code, 0, done.stdout[-600:])
        self.assertEqual(report["result"], {"status": "PASS", "code": "SELF_TEST"})
        self.assertEqual(len(report["checks"]), 12)
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["syscalls"], {"status": "AVAILABLE"})
        self.assertIn("kernel", report["environment"])

    def listener(self, ptracer_any, dup=False):
        """A loopback listener that is the probe's sibling, not its child (as Ollama is on the phone)."""
        allow = ("import ctypes;ctypes.CDLL(None).prctl(0x59616D61,ctypes.c_ulong(2**64-1),0,0,0);"
                 if ptracer_any else "")
        extra = "d=os.dup(s.fileno());" if dup else ""
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c",
                                  allow + "import socket,os,sys;s=socket.socket();s.bind(('127.0.0.1',0));"
                                  "s.listen(2);" + extra +
                                  "print(os.getpid(),s.getsockname()[1],flush=True);sys.stdin.read()"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (child.kill(), child.wait(5), child.stdin.close(), child.stdout.close()))
        pid, port = map(int, child.stdout.readline().split())
        return child, pid, port

    def test_target_mode_under_yama_without_exception_is_blocked(self):
        _, pid, port = self.listener(ptracer_any=False)
        code, report, _ = run_probe("--target-pid", str(pid), "--expect", f"127.0.0.1:{port}")
        if yama_scope() == 1:      # the sibling target did not allow us as tracer: the kernel must refuse
            self.assertEqual((code, report["result"]), (2, {"status": "BLOCKED", "code": "PIDFD_GETFD_EPERM"}))
            return
        # Yama is not restricting here: no skip. The probe may conclude, but only on a complete scan.
        self.assertIn(code, (0, 2), report["result"])
        if code == 0:
            self.assertEqual(report["result"]["code"], "LISTENER_OWNED")
            self.assertEqual(report["sharing"]["scope"], "ALL_PROCESSES_INSPECTED")
        else:
            self.assertEqual(report["result"]["status"], "BLOCKED")

    def test_target_mode_finds_owned_listener_and_rejects_wrong_port(self):
        child, pid, port = self.listener(ptracer_any=True)
        code, report, done = run_probe("--target-pid", str(pid), "--expect", f"127.0.0.1:{port}")
        if code == 2 and process_observation_limited(report):
            env_unmet(f"runner policy blocks target inspection: {report['result'].get('code')}")
        self.assertEqual(code, 0, done.stdout[-600:])
        self.assertEqual(report["result"]["code"], "LISTENER_OWNED")
        self.assertEqual(report["expect"]["port_hex"], f"{port:04X}")
        code, report, _ = run_probe("--target-pid", str(pid), "--expect", f"127.0.0.1:{port ^ 1}")
        self.assertEqual((code, report["result"]["code"]), (1, "NO_UNIQUE_LISTENER"))
        # still alive and still listening: the probe changed nothing on the target
        self.assertIsNone(child.poll())
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass

    def test_target_with_duplicated_descriptor_is_one_listener(self):
        """F-9 in the probe: two descriptors of one socket must not read as 'no unique listener'."""
        _, pid, port = self.listener(ptracer_any=True, dup=True)
        code, report, done = run_probe("--target-pid", str(pid), "--expect", f"127.0.0.1:{port}")
        if code == 2 and process_observation_limited(report):
            env_unmet(f"runner policy blocks target inspection: {report['result'].get('code')}")
        self.assertEqual(code, 0, done.stdout[-600:])
        self.assertEqual(report["result"]["code"], "LISTENER_OWNED")
        self.assertEqual(len(report["result"]["fds"]), 2)
        self.assertEqual(report["sharing"]["scope"], "ALL_PROCESSES_INSPECTED")

    def test_port_hex_constant(self):
        self.assertEqual(f"{11434:04X}", "2CAA")


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def load_tests(loader, standard_tests, pattern):
    """HG_L5_REAL_KERNEL_GATE=external leaves the real-kernel ProbeRunTests out of a discover run: they belong to
    the separate capability-gated CI job (`l5-capability-gate`, HG_REQUIRE_PROC_TESTS=1) and are reported there,
    honestly, as BLOCKED when the runner cannot observe every process. They are NOT_RUN in this run: neither
    skipped nor passed. Default (variable unset): everything is collected, as before."""
    if os.environ.get("HG_L5_REAL_KERNEL_GATE") != "external":
        return standard_tests
    return unittest.TestSuite(test for test in _flatten(standard_tests) if not isinstance(test, ProbeRunTests))


if __name__ == "__main__":
    unittest.main()
