"""WS-04 oracle: code.symbols cannot crash the HG process on a small thread stack.

The gateway runs adapters on worker threads. On Termux/Android (Python 3.14.8) a worker
thread has a small platform default stack, and CPython's C parser overflowed it: ast.parse
of a 5000-term sum killed the process with SIGSEGV (observed 2026-11-12 on the owner's
phone: the HG suite died at exit 139 in the code.symbols oracle), where the main thread
raises RecursionError. In `hg serve` that is the whole service.

The oracle reruns the code.symbols content oracle (real tasks through BrainOrchestrator
-> ActionGateway -> adapter) in a child process whose default thread stack is set small,
as on Android, so a crash fails this test instead of the suite. The child must finish
with every test passing, for each stack size.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHILD = (
    "import sys, threading\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "threading.stack_size(int(sys.argv[2]))\n"
    "import unittest\n"
    "unittest.main(module='hg.tests.test_code_tools_content_oracle',"
    " argv=['oracle', 'CodeSymbolsContentOracle'], exit=True)\n"
)


class CodeSymbolsThreadStackOracle(unittest.TestCase):
    def run_child(self, stack_bytes):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        return subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, str(REPO), str(stack_bytes)],
                              capture_output=True, text=True, timeout=300, env=env, cwd=str(REPO))

    def test_symbol_oracle_passes_on_small_worker_stacks(self):
        for kib in (256, 512):
            with self.subTest(stack_kib=kib):
                result = self.run_child(kib * 1024)
                self.assertEqual(result.returncode, 0,
                                 f"exit {result.returncode} (negative = killed by signal)\n{result.stderr[-2000:]}")
                self.assertIn("OK", result.stderr.strip().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
