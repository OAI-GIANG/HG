"""The standalone L5 probe (deploy/termux/l5_probe.py), run as a separate process on the real kernel.

It must stay independent of HG (no `hg` import) so it can run on the phone from any checkout."""
import ast
import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

from hg.assistant import attest as at

PROBE = Path(__file__).resolve().parents[2] / "deploy" / "termux" / "l5_probe.py"
REQUIRE = os.environ.get("HG_REQUIRE_PROC_TESTS") == "1"
LINUX = sys.platform.startswith("linux") and os.path.isdir("/proc/self/fd")


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


@unittest.skipUnless(LINUX, "Linux /proc required")
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

    def test_target_mode_finds_owned_listener_and_rejects_wrong_port(self):
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c",
                                  "import socket,os,sys;s=socket.socket();s.bind(('127.0.0.1',0));s.listen(2);"
                                  "print(os.getpid(),s.getsockname()[1],flush=True);sys.stdin.read()"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (child.kill(), child.wait(5), child.stdin.close(), child.stdout.close()))
        pid, port = map(int, child.stdout.readline().split())
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

    def test_port_hex_constant(self):
        self.assertEqual(f"{11434:04X}", "2CAA")


if __name__ == "__main__":
    unittest.main()
