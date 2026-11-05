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

    def run_target(self, row=None, errors=None, sharing=None):
        row = self.row() if row is None else row
        errors = [] if errors is None else errors
        sharing = ({"uninspectable": {"same_uid": 0, "root": 0, "other_uid": 0, "unknown": 0},
                    "unreadable_descriptors": 0, "proc_hidepid": None, "scope": "ALL_PROCESSES_INSPECTED"}
                   if sharing is None else sharing)
        report = {}
        with mock.patch.object(PROBE_MODULE.os, "readlink", return_value="/usr/bin/ollama"), \
             mock.patch.object(PROBE_MODULE, "status_fields", return_value={}), \
             mock.patch.object(PROBE_MODULE, "starttime", return_value=77), \
             mock.patch.object(PROBE_MODULE, "pidfd_open", return_value=999), \
             mock.patch.object(PROBE_MODULE.os, "close"), \
             mock.patch.object(PROBE_MODULE, "inspect", return_value=([row], errors)), \
             mock.patch.object(PROBE_MODULE, "exited", return_value=False), \
             mock.patch.object(PROBE_MODULE, "holders", return_value=([], sharing)):
            code = PROBE_MODULE.target(report, 123, "127.0.0.1:11434")
        return code, report

    def test_platform_gate_accepts_android_and_linux_only(self):
        self.assertTrue(PROBE_MODULE.supported_platform("android"))
        self.assertTrue(PROBE_MODULE.supported_platform("linux"))
        self.assertFalse(PROBE_MODULE.supported_platform("darwin"))

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


@unittest.skipUnless(PROC_PLATFORM, "Linux/Android /proc required")
class ProbeRunTests(unittest.TestCase):
    def setUp(self):
        cap = at.capability()
        if cap["status"] != "PASS":
            if REQUIRE:
                self.fail(f"pidfd_getfd unavailable: {cap['code']}")
            self.skipTest(f"pidfd_getfd unavailable: {cap['code']}")

    def test_self_test_passes_every_check(self):
        code, report, done = run_probe()
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
        if yama_scope() != 1:
            self.skipTest("Yama ptrace_scope is not 1 here")
        _, pid, port = self.listener(ptracer_any=False)
        code, report, _ = run_probe("--target-pid", str(pid), "--expect", f"127.0.0.1:{port}")
        self.assertEqual((code, report["result"]), (2, {"status": "BLOCKED", "code": "PIDFD_GETFD_EPERM"}))

    def test_target_mode_finds_owned_listener_and_rejects_wrong_port(self):
        child, pid, port = self.listener(ptracer_any=True)
        code, report, done = run_probe("--target-pid", str(pid), "--expect", f"127.0.0.1:{port}")
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
        self.assertEqual(code, 0, done.stdout[-600:])
        self.assertEqual(report["result"]["code"], "LISTENER_OWNED")
        self.assertEqual(len(report["result"]["fds"]), 2)
        self.assertIn(report["sharing"]["scope"], ("ALL_PROCESSES_INSPECTED", "PARTIAL"))

    def test_port_hex_constant(self):
        self.assertEqual(f"{11434:04X}", "2CAA")


if __name__ == "__main__":
    unittest.main()
