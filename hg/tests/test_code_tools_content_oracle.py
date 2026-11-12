"""WS-04 oracle: code.search, code.symbols and code.diff report what the files contain.

These read-only tools feed planning and research. Their answers are claims about files:
"identical", "no match", "this match is on line N", "these are the definitions". A claim
must be true of the bytes on disk, or the tool must say what it did not read:

* code.diff `identical` is true only when the file's text is exactly the provided text; a
  missing final newline or different line endings is a difference, shown in the diff;
* code.search counts lines the way Python, editors and `grep -n` do (LF, CRLF, CR); form
  feed, U+001C..U+001E, U+0085 and U+2028/U+2029 are characters inside a line;
* a file the walk did not read (not UTF-8, over the size bound, a symlink, a FIFO) is
  listed in `files_skipped` with a reason, so "no match" is never silently "not read";
  a search or symbol index started on a single unreadable file is a known failure;
* a file that exhausts the Python parser's recursion is reported in `syntax_errors`, not
  an unknown outcome that blocks the runtime;
* a pattern containing a line break (it can never match one line) is refused.

Each case runs a real task through BrainOrchestrator -> ActionGateway -> adapter. Controls:
an exact copy diffs as identical, ordinary searches and symbol indexes are unchanged.
"""
import os
import unittest

from hg.tests.test_file_adapter_path_oracle import Base, outcomes, step
from hg.tools import code as code_tools


class CodeToolsContentBase(Base):
    def reset(self):
        """A fresh work directory and runtime (one task per runtime) for the next subtest."""
        self.tearDown()
        self.setUp()

    def put(self, files):
        for rel, data in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def run_one(self, s):
        seen = []

        def verifier(snapshot):
            seen.extend(o for o in snapshot["outcomes"] if o.get("tool") == s["tool"])
            return True, "any"
        rt, final = self.run_steps([s], verifiers={"AC-1": verifier})
        return rt, final, seen

    def observed(self, s):
        rt, final, seen = self.run_one(s)
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED",
                         [(p["status"], p.get("error")) for p in outcomes(rt)])
        self.assertEqual(len(seen), 1)
        return seen[0]["observed"]


class CodeDiffContentOracle(CodeToolsContentBase):
    PATH = "out/a.txt"

    def diff(self, data, against):
        self.put({self.PATH: data})
        return self.observed(step("code.diff", "READ", self.PATH, against=against))

    def assert_different(self, data, against):
        obs = self.diff(data, against)
        self.assertFalse(obs["identical"], obs)
        self.assertTrue(obs["diff"], obs)
        self.assertGreater(obs["added"] + obs["removed"], 0, obs)
        return obs

    def test_missing_final_newline_is_a_difference(self):
        self.assert_different(b"a\nb\n", "a\nb")

    def test_extra_final_newline_is_a_difference(self):
        self.assert_different(b"a\nb", "a\nb\n")

    def test_crlf_against_lf_is_a_difference(self):
        self.assert_different(b"a\r\nb\r\n", "a\nb\n")

    def test_cr_against_lf_is_a_difference(self):
        self.assert_different(b"a\rb\r", "a\nb\n")

    def test_form_feed_is_not_a_line_break(self):
        self.assert_different(b"a\x0cb\n", "a\nb\n")

    def test_long_diff_reports_truncation(self):
        lines = "".join(f"line {i}\n" for i in range(3000))
        obs = self.diff(lines.encode(), "")
        self.assertFalse(obs["identical"])
        self.assertEqual(obs["added"], 3000)
        self.assertTrue(obs["truncated"], {k: v for k, v in obs.items() if k != "diff"})

    # ---- controls ----

    def test_control_exact_copy_is_identical(self):
        for text in ("a\nb\n", "a\r\nb\r\n", "a\nb", "", "Xin chào 🌏\n"):
            with self.subTest(text=text):
                self.reset()
                obs = self.diff(text.encode("utf-8"), text)
                self.assertTrue(obs["identical"], obs)
                self.assertEqual(obs["diff"], [])
                self.assertEqual((obs["added"], obs["removed"]), (0, 0))
                self.assertFalse(obs["truncated"])

    def test_control_changed_line_counts(self):
        obs = self.diff(b"a\nB\nc\n", "a\nb\nc\n")
        self.assertFalse(obs["identical"])
        self.assertEqual((obs["added"], obs["removed"]), (1, 1))


class CodeSearchContentOracle(CodeToolsContentBase):
    def search(self, files, pattern, path="out/s"):
        self.put(files)
        return self.observed(step("code.search", "READ", path, pattern=pattern))

    def test_line_numbers_follow_python_and_grep(self):
        # Every one of these separators is inside line 1; the match is on line 2.
        for sep in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "):
            with self.subTest(sep=repr(sep)):
                self.reset()
                obs = self.search({"out/s/a.py": f"x{sep}y\nkey = 1\n".encode("utf-8")}, "key")
                self.assertEqual([(m["file"], m["line"]) for m in obs["matches"]], [("out/s/a.py", 2)])

    def test_match_text_keeps_the_whole_line(self):
        obs = self.search({"out/s/a.py": "x key = 1\n".encode("utf-8")}, "key")
        self.assertEqual(obs["match_count"], 1)
        self.assertEqual(obs["matches"][0]["line"], 1)
        self.assertEqual(obs["matches"][0]["text"], "x key = 1")

    def test_cr_and_crlf_lines_are_counted(self):
        obs = self.search({"out/s/a.py": b"a\rb\r\nkey\n"}, "key")
        self.assertEqual([m["line"] for m in obs["matches"]], [3])

    def test_unread_files_are_listed_with_a_reason(self):
        files = {"out/s/latin1.py": "key = 'café'\n".encode("latin-1"),
                 "out/s/big.py": b"key\n" + b"#" * code_tools.MAX_FILE_BYTES,
                 "out/s/ok.py": b"x = 1\n"}
        obs = self.search(files, "key")
        self.assertEqual(obs["match_count"], 0)
        self.assertEqual(obs["files_scanned"], 1)
        skipped = {s["file"]: s["reason"] for s in obs["files_skipped"]}
        self.assertEqual(set(skipped), {"out/s/latin1.py", "out/s/big.py"})
        self.assertIn("UTF-8", skipped["out/s/latin1.py"])
        self.assertIn("bytes", skipped["out/s/big.py"])

    def test_symlink_in_walk_is_listed_without_its_target(self):
        self.put({"out/s/ok.py": b"key = 1\n"})
        os.symlink(self.secret, self.root / "out" / "s" / "link.py")
        obs = self.observed(step("code.search", "READ", "out/s", pattern="key"))
        self.assertEqual(obs["match_count"], 1)
        self.assertEqual([s["file"] for s in obs["files_skipped"]], ["out/s/link.py"])
        self.assertNotIn("OUT-OF-SCOPE-SECRET", repr(obs))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "platform has no FIFOs")
    def test_fifo_in_walk_is_listed(self):
        self.put({"out/s/ok.py": b"key = 1\n"})
        os.mkfifo(self.root / "out" / "s" / "pipe.py")
        obs = self.observed(step("code.search", "READ", "out/s", pattern="key"))
        self.assertEqual([s["file"] for s in obs["files_skipped"]], ["out/s/pipe.py"])

    def test_search_of_a_single_unreadable_file_is_a_known_failure(self):
        self.put({"out/s/latin1.py": "key = 'café'\n".encode("latin-1")})
        rt, final, _seen = self.run_one(step("code.search", "READ", "out/s/latin1.py", pattern="key"))
        self.assert_refused(rt, final)
        self.assertEqual({p["status"] for p in outcomes(rt)}, {"FAILED"})     # retried, never UNKNOWN

    def test_pattern_with_a_line_break_is_refused(self):
        self.put({"out/s/a.py": b"a\nb\n"})
        for pattern in ("a\nb", "a\rb", "a\r\n"):
            with self.subTest(pattern=repr(pattern)):
                self.reset()
                self.put({"out/s/a.py": b"a\nb\n"})
                rt, final, _seen = self.run_one(step("code.search", "READ", "out/s", pattern=pattern))
                self.assert_refused(rt, final)
                self.assertNotIn("UNKNOWN", [p["status"] for p in outcomes(rt)])

    # ---- controls ----

    def test_control_plain_search(self):
        obs = self.search({"out/s/a.py": b"x = 1\nkey = 2\n", "out/s/b.py": "key ở đây\n".encode()}, "key")
        self.assertEqual([(m["file"], m["line"]) for m in obs["matches"]],
                         [("out/s/a.py", 2), ("out/s/b.py", 1)])
        self.assertEqual(obs["files_scanned"], 2)
        self.assertEqual(obs["files_skipped"], [])


class CodeSymbolsContentOracle(CodeToolsContentBase):
    def symbols(self, files, path="out/s"):
        self.put(files)
        return self.observed(step("code.symbols", "READ", path))

    def test_parser_recursion_is_a_syntax_error_entry_not_unknown(self):
        deep = ("x = " + "+".join(["1"] * 200_000) + "\n").encode()
        obs = self.symbols({"out/s/deep.py": deep, "out/s/ok.py": b"def f():\n    pass\n"})
        self.assertEqual([s["qualname"] for s in obs["symbols"]], ["f"])
        self.assertEqual([e["file"] for e in obs["syntax_errors"]], ["out/s/deep.py"])

    def test_long_expression_that_parses_is_indexed(self):
        # A 5000-term sum parses in CPython; on a small worker-thread stack (Termux)
        # the parser crashed the process instead (see test_code_symbols_thread_stack_oracle).
        src = ("TABLE = " + "+".join(["1"] * 5000) + "\n\ndef f():\n    pass\n").encode()
        obs = self.symbols({"out/s/long.py": src})
        self.assertEqual([s["qualname"] for s in obs["symbols"]], ["f"])
        self.assertEqual(obs["syntax_errors"], [])

    def test_parser_stack_overflow_is_a_syntax_error_entry_not_unknown(self):
        # CPython reports a too-deep parser stack as MemoryError, not SyntaxError.
        deep = ("x = " + "-" * 6000 + "1\n").encode()
        obs = self.symbols({"out/s/deep.py": deep, "out/s/ok.py": b"def f():\n    pass\n"})
        self.assertEqual([s["qualname"] for s in obs["symbols"]], ["f"])
        self.assertEqual([e["file"] for e in obs["syntax_errors"]], ["out/s/deep.py"])

    def test_deep_expression_that_parses_is_indexed(self):
        # Parses, but deeper than Python's own recursion limit: the index must not recurse.
        src = ("def f():\n    return " + "-" * 1500 + "1\n\ndef g():\n    h()\n").encode()
        obs = self.symbols({"out/s/deep.py": src})
        self.assertEqual([s["qualname"] for s in obs["symbols"]], ["f", "g"])
        self.assertEqual(obs["syntax_errors"], [])

    def test_deeply_nested_definitions_are_indexed(self):
        # 90 nested classes parse (the indentation limit is 100); every one is indexed.
        src = "".join("    " * i + f"class C{i}:\n" for i in range(90)) + "    " * 90 + "pass\n"
        obs = self.symbols({"out/s/nest.py": src.encode()})
        self.assertEqual(obs["symbol_count"], 90)
        self.assertEqual(obs["symbols"][-1]["qualname"], ".".join(f"C{i}" for i in range(90)))

    def test_non_utf8_python_file_is_listed(self):
        obs = self.symbols({"out/s/latin1.py": "def f(): return 'café'\n".encode("latin-1"),
                            "out/s/ok.py": b"def g():\n    pass\n"})
        self.assertEqual([s["qualname"] for s in obs["symbols"]], ["g"])
        self.assertEqual([s["file"] for s in obs["files_skipped"]], ["out/s/latin1.py"])

    def test_index_of_a_single_unreadable_file_is_a_known_failure(self):
        self.put({"out/s/latin1.py": "def f(): return 'café'\n".encode("latin-1")})
        rt, final, _seen = self.run_one(step("code.symbols", "READ", "out/s/latin1.py"))
        self.assert_refused(rt, final)
        self.assertEqual({p["status"] for p in outcomes(rt)}, {"FAILED"})     # retried, never UNKNOWN

    # ---- controls ----

    def test_control_plain_index(self):
        obs = self.symbols({"out/s/a.py": b"class Box:\n    def open(self):\n        greet()\n",
                            "out/s/b.txt": b"not python\xff\n"})
        self.assertEqual([s["qualname"] for s in obs["symbols"]], ["Box", "Box.open"])
        self.assertEqual(obs["top_calls"], [["greet", 1]] if isinstance(obs["top_calls"][0], list)
                         else [("greet", 1)])
        self.assertEqual(obs["files_skipped"], [])       # non-.py files are not candidates
        self.assertEqual(obs["syntax_errors"], [])


if __name__ == "__main__":
    unittest.main()
