"""WS-04 oracle: bounded log-window anchors name the lines an editor shows.

`hg.verification.bounded.extract_log_window` sends a small excerpt to a model while the raw
evidence is kept separately. Each excerpt line is labelled `[L#]` and the report carries
`line_ranges` and `matched_error_lines`, so a reader can go from the excerpt back to the raw
log with `grep -n`, `less -N` or an editor. Only LF, CRLF and CR end a line there;
`str.splitlines()` also splits on VT, FF, FS, GS, RS, NEL, U+2028 and U+2029, so one of those
characters (a form feed between pages of output, a pasted U+2028) would shift every later
anchor away from the raw line it claims to quote.

The oracle counts lines independently on the raw bytes (LF, CRLF, CR) and checks, for both
selections (error context and tail fallback):
- every `[L#]` line quotes raw line # (ANSI escapes and NUL removed, as documented);
- `matched_error_lines` are the raw lines holding the error marker;
- `line_ranges` cover exactly the labelled lines.
Controls: LF, CRLF, CR and mixed endings, with and without a final newline.
"""
import re
import unittest

from hg.verification.bounded import extract_log_window

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LABEL = re.compile(r"\[L(\d+)\] ?(.*)", re.S)

# Characters str.splitlines() treats as line ends but editors / grep -n do not.
NOT_LINE_ENDS = {"VT": "\x0b", "FF": "\x0c", "FS": "\x1c", "GS": "\x1d", "RS": "\x1e",
                 "NEL": "\x85", "LS": " ", "PS": " "}
ENDINGS = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}


def editor_lines(raw):
    """Lines as editors and `grep -n` count them, from the raw bytes."""
    parts = re.split(r"\r\n|\r|\n", raw.decode("utf-8", errors="replace"))
    if parts and parts[-1] == "":
        parts.pop()
    return parts or [""]


def labelled(excerpt):
    """[(n, text)] for every labelled excerpt line (split only on the renderer's LF)."""
    out = []
    for row in excerpt.split("\n"):
        m = _LABEL.fullmatch(row)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


class LogWindowLineAnchorOracle(unittest.TestCase):
    def check(self, raw, **kwargs):
        lines = editor_lines(raw)
        report = extract_log_window(raw, max_output_bytes=64 * 1024, **kwargs)
        rows = labelled(report["excerpt"])
        self.assertTrue(rows, "excerpt has no labelled lines")
        for n, text in rows:
            self.assertLessEqual(n, len(lines), f"[L{n}] is past the last raw line ({len(lines)})")
            self.assertEqual(text, _ANSI.sub("", lines[n - 1]).replace("\0", ""), f"[L{n}] text")
        expected_matches = [i for i, line in enumerate(lines, 1) if "ERROR" in line or "Error" in line]
        if report["selection"] == "error-context":
            self.assertEqual(report["matched_error_lines"], expected_matches[:kwargs.get("max_matches", 8)])
        covered = [n for start, end in report["line_ranges"] for n in range(start, end + 1)]
        self.assertEqual(covered, [n for n, _ in rows])
        return report

    def payload(self, middle, ending, *, final=True, error=True):
        rows = [
            "INFO start of run",
            f"INFO page one{middle}page two of the same line",
            "INFO step two",
            "INFO step three",
            "ERROR disk quota exceeded on /data" if error else "INFO step four",
            "INFO step five",
            "INFO done",
        ]
        text = ending.join(rows) + (ending if final else "")
        return text.encode("utf-8")

    def test_error_context_anchors_ignore_non_line_end_characters(self):
        for cname, char in NOT_LINE_ENDS.items():
            for ename, ending in ENDINGS.items():
                with self.subTest(char=cname, ending=ename):
                    report = self.check(self.payload(char, ending), context_lines=1)
                    self.assertEqual(report["selection"], "error-context")
                    self.assertEqual(report["matched_error_lines"], [5])
                    self.assertEqual(report["line_ranges"], [[4, 6]])

    def test_tail_fallback_anchors_ignore_non_line_end_characters(self):
        for cname, char in NOT_LINE_ENDS.items():
            for ename, ending in ENDINGS.items():
                with self.subTest(char=cname, ending=ename):
                    report = self.check(self.payload(char, ending, error=False), tail_lines=7)
                    self.assertEqual(report["selection"], "tail-fallback")
                    self.assertEqual(report["line_ranges"], [[1, 7]])

    def test_controls_plain_endings(self):
        for ename, ending in ENDINGS.items():
            for final in (True, False):
                with self.subTest(ending=ename, final_newline=final):
                    report = self.check(self.payload(" ", ending, final=final), context_lines=1)
                    self.assertEqual(report["line_ranges"], [[4, 6]])
        mixed = b"INFO a\r\nINFO b\rINFO c\nERROR d\r\nINFO e"
        report = self.check(mixed, context_lines=1)
        self.assertEqual(report["matched_error_lines"], [4])
        self.assertEqual(report["line_ranges"], [[3, 5]])

    def test_control_ansi_and_nul_are_stripped_from_the_quoted_line(self):
        raw = b"INFO a\n\x1b[31mERROR\x1b[0m red\x00 text\nINFO c\n"
        report = self.check(raw, context_lines=1)
        self.assertIn("[L2] ERROR red text", report["excerpt"])


if __name__ == "__main__":
    unittest.main()
