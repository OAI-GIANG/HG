"""WS-04 oracle: `hg summarize` line anchors name the lines an editor shows.

`hg summarize` promises that every output sentence carries the source lines it comes from
([L#] / [L#-L#]) and that HG checks model sentences against the lines they cite. The owner
reads those numbers in an editor, `grep -n` or `less -N`. Only LF, CRLF and CR end a line
there; `str.splitlines()` also splits on VT, FF, FS, GS, RS, NEL, U+2028 and U+2029, so a file
with any of those (a form feed between pages, a pasted U+2028) would get every later anchor
shifted, quoted sentences pointing at the wrong line, and model citations judged against the
wrong text.

The oracle counts lines independently (LF, CRLF, CR on the raw bytes) and checks:
- every extractive sentence is quoted from the line it names;
- a model sentence citing the real line is ANCHORED, and a citation past the real last line
  is BADCITE;
- the model is shown the real line numbers.
Controls: LF, CRLF, CR, mixed endings and a missing final newline.
"""
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from hg.assistant import summarize as sm
from hg.assistant import textvi
from hg.brain.providers import ModelRouter


def editor_lines(raw):
    """Lines as editors and `grep -n` count them, from the raw bytes."""
    text = textvi.nfc(raw.decode("utf-8"))
    parts = re.split(r"\r\n|\r|\n", text)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


class FakeModel:
    name, model, offline, supports_stream = "ollama", "fake:1b", True, True
    cost_per_mtok = (0.0, 0.0)

    def __init__(self, text):
        self.text, self.requests = text, []

    def complete(self, request, on_delta=None):
        self.requests.append(request)
        return {"text": self.text, "provider": self.name, "model": self.model,
                "usage": {"input_tokens": 1, "output_tokens": 1}, "finish_reason": "stop"}


FIRST = "Nhóm dự án thống nhất phát hành bản thử nghiệm trên điện thoại."
INLINE = "Trang sau ghi ngân sách thử nghiệm model cho nhóm dự án."
LAST = "Anh Minh viết hướng dẫn cài đặt cho nhóm dự án bằng tiếng Việt."

# Characters str.splitlines() treats as line ends but editors / grep -n do not.
NOT_LINE_ENDS = {"VT": "\x0b", "FF": "\x0c", "FS": "\x1c", "GS": "\x1d", "RS": "\x1e",
                 "NEL": "\x85", "LS": " ", "PS": " "}
ENDINGS = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}


class SummarizeLineAnchorOracle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-sum-anchor-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, text):
        path = self.tmp / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def check_file(self, path, last_line_no):
        raw = path.read_bytes()
        lines = editor_lines(raw)
        text, info = sm.read_input(str(path))
        self.assertEqual(info["bytes"], len(raw))
        items = sm.extractive(text, max_sentences=10)
        self.assertTrue(items)
        for item in items:
            first, last = item["lines"]
            self.assertEqual(first, last)
            self.assertLessEqual(first, len(lines), item)
            self.assertIn(item["sentence"], lines[first - 1], item)
        anchored = {i["sentence"]: i["lines"][0] for i in items}
        self.assertEqual(anchored.get(LAST), last_line_no, anchored)

        reply = f"{LAST[:-1]} [L{last_line_no}]. {FIRST[:-1]} [L{len(lines) + 1}]."
        model = FakeModel(reply)
        got, _dropped, _resp = sm.with_model(text, ModelRouter([model], max_retries=0))
        self.assertEqual([i["label"] for i in got], ["ANCHORED", "BADCITE"], got)
        self.assertEqual(got[0]["lines"], [last_line_no, last_line_no])
        shown = model.requests[0]["messages"][0]["content"]
        self.assertIn(f"\nL{last_line_no}: {LAST}\n", shown)
        self.assertNotIn(f"L{len(lines) + 1}:", shown)

    def test_characters_that_do_not_end_a_line_keep_later_anchors(self):
        for label, ch in NOT_LINE_ENDS.items():
            for ending_label, ending in ENDINGS.items():
                with self.subTest(char=label, ending=ending_label):
                    body = f"{FIRST}{ch}{INLINE}{ending}{ending}{LAST}{ending}"
                    self.check_file(self.write(f"{label}-{ending_label}.txt", body), 3)

    def test_controls_line_endings(self):
        for ending_label, ending in ENDINGS.items():
            with self.subTest(ending=ending_label):
                body = f"{FIRST}{ending}{INLINE}{ending}{ending}{LAST}{ending}"
                self.check_file(self.write(f"plain-{ending_label}.txt", body), 4)
        with self.subTest(ending="mixed, no final newline"):
            body = f"{FIRST}\r\n{INLINE}\r\r{LAST}"
            self.check_file(self.write("mixed.txt", body), 4)


if __name__ == "__main__":
    unittest.main()
