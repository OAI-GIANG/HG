"""WS-04 oracle: a number in an answer is the same number the note says.

`hg ask` and `hg check` promise that a sentence is KHỚP/NOTE only when "every number, date,
proper name and negation the sentence asserts is consistent with that note", and call a
different number "the most dangerous error in personal notes" (CONFLICT). The owner acts on
these numbers: a dose, an appointment date, a meeting time, a phone number, a door code.

The oracle states, independently of `textvi`, which written forms denote the same value and
which do not, and checks the labels HG gives through its real paths: `grounding.check_sentence`
with the question (the `hg ask` path) and `check.check` over a real Notebook (the `hg check`
path, no question). Different values must never be NOTE/KHỚP:
- a decimal is not the integer made of its digits ("0,5 viên" is not "5 viên");
- day/month order matters ("5/9" is 5 September, "9/5" is 9 May);
- hour:minute order matters ("8:05" is not "5:08");
- a leading zero is part of an identifier ("0912345678", "0420" are not "912345678", "420");
- a part of a time is not the time ("5 giờ" is not supported by "15:05").
Controls (same value, different writing) must stay NOTE: DMY and ISO dates, a day/month that
a full date in the note contains, "08:05" and "8:05", "8 giờ 30" and "8:30", "8 giờ" and
"8:00", Vietnamese and English decimal commas, thousands grouping.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from hg.assistant import evaluate, grounding
from hg.assistant.check import check
from hg.assistant.notes import Notebook

# (note, answer sentence, question): the answer states a DIFFERENT value than the note.
DIFFERENT = [
    ("Uống 0,5 viên thuốc huyết áp mỗi sáng.", "Uống 5 viên thuốc huyết áp mỗi sáng.",
     "uống mấy viên thuốc huyết áp mỗi sáng"),
    ("Uống 0.5 viên thuốc huyết áp mỗi sáng.", "Uống 5 viên thuốc huyết áp mỗi sáng.",
     "uống mấy viên thuốc huyết áp mỗi sáng"),
    ("Liều siro ho cho bé là 2,5 ml.", "Liều siro ho cho bé là 25 ml.", "liều siro ho cho bé"),
    ("Hẹn khám răng ngày 5/9.", "Hẹn khám răng ngày 9/5.", "hẹn khám răng ngày nào"),
    ("Hẹn khám răng ngày 05/09/2026.", "Hẹn khám răng ngày 2026-05-09.", "hẹn khám răng ngày nào"),
    ("Họp phụ huynh lúc 8:05 tối thứ bảy.", "Họp phụ huynh lúc 5:08 tối thứ bảy.",
     "họp phụ huynh lúc mấy giờ tối thứ bảy"),
    ("Số điện thoại bác sĩ Lan là 0912345678.", "Số điện thoại bác sĩ Lan là 912345678.",
     "số điện thoại bác sĩ Lan"),
    ("Mã cửa nhà kho là 0420.", "Mã cửa nhà kho là 420.", "mã cửa nhà kho"),
    ("Họp phụ huynh lúc 15:05 tối thứ bảy.", "Họp phụ huynh lúc 5 giờ tối thứ bảy.",
     "họp phụ huynh lúc mấy giờ tối thứ bảy"),
]

# (note, answer sentence, question): the answer states the SAME value, written differently.
SAME = [
    ("Hẹn khám răng ngày 2026-09-05.", "Hẹn khám răng ngày 05/09/2026.", "hẹn khám răng ngày nào"),
    ("Hẹn khám răng ngày 05/09/2026.", "Hẹn khám răng ngày 5/9.", "hẹn khám răng ngày nào"),
    ("Họp phụ huynh lúc 08:05 tối thứ bảy.", "Họp phụ huynh lúc 8:05 tối thứ bảy.",
     "họp phụ huynh lúc mấy giờ tối thứ bảy"),
    ("Họp phụ huynh lúc 8 giờ 30 tối thứ bảy.", "Họp phụ huynh lúc 8:30 tối thứ bảy.",
     "họp phụ huynh lúc mấy giờ tối thứ bảy"),
    ("Họp phụ huynh lúc 8:00 tối thứ bảy.", "Họp phụ huynh lúc 8 giờ tối thứ bảy.",
     "họp phụ huynh lúc mấy giờ tối thứ bảy"),
    ("Uống 0,5 viên thuốc huyết áp mỗi sáng.", "Uống 0.5 viên thuốc huyết áp mỗi sáng.",
     "uống mấy viên thuốc huyết áp mỗi sáng"),
    ("Xe đã chạy 18.200 km.", "Xe đã chạy 18200 km.", "xe đã chạy bao nhiêu km"),
    ("Ngân sách tháng là 4.000.000 đồng.", "Ngân sách tháng là 4,000,000 đồng.", "ngân sách tháng"),
    ("Hẹn khám răng ngày 5 tháng này.", "Hẹn khám răng ngày 05 tháng này.", "hẹn khám răng ngày nào"),
]


class AskPathNumberIdentity(unittest.TestCase):
    """`hg ask`: grounding.check_sentence with the question."""

    def test_a_different_value_is_never_note(self):
        for note, answer, question in DIFFERENT:
            with self.subTest(answer=answer, note=note):
                r = grounding.check_sentence(answer, {"N1": note}, question=question)
                self.assertNotEqual(r["label"], "NOTE", r)

    def test_a_different_value_close_to_the_note_is_conflict_without_a_question(self):
        for note, answer, _question in DIFFERENT:
            with self.subTest(answer=answer, note=note):
                r = grounding.check_sentence(answer, {"N1": note})
                self.assertEqual(r["label"], "CONFLICT", r)

    def test_the_same_value_written_differently_stays_note(self):
        for note, answer, question in SAME:
            with self.subTest(answer=answer, note=note):
                r = grounding.check_sentence(answer, {"N1": note}, question=question)
                self.assertEqual((r["label"], r["note"]), ("NOTE", "N1"), r)


class CheckPathNumberIdentity(unittest.TestCase):
    """`hg check`: check.check over a real Notebook, no question."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _label(self, note, text):
        nb = Notebook(self.tmp / f"home{len(list(self.tmp.iterdir()))}")
        nb.add(note, origin="test")
        result = check(text, nb)
        self.assertEqual(len(result["sentences"]), 1, result)
        return result["sentences"][0]

    def test_a_different_value_is_conflict(self):
        for note, answer, _question in DIFFERENT:
            with self.subTest(answer=answer, note=note):
                self.assertEqual(self._label(note, answer)["label"], "CONFLICT")

    def test_the_same_value_written_differently_is_note(self):
        for note, answer, _question in SAME:
            with self.subTest(answer=answer, note=note):
                self.assertEqual(self._label(note, answer)["label"], "NOTE")


class EvalKeyNumberIdentity(unittest.TestCase):
    """`hg eval` scores an answer by whether it contains the expected key."""

    def test_key_with_a_different_value_is_absent(self):
        for key, answer in [("0,5 viên", "Uống 5 viên."), ("5/9", "Ngày 9/5."), ("8:05", "Lúc 5:08."),
                            ("0912345678", "Số 912345678."), ("5", "Uống 0,5 viên."), ("420", "Mã 0420.")]:
            with self.subTest(key=key):
                self.assertFalse(evaluate.key_present(key, answer))

    def test_key_with_the_same_value_is_present(self):
        for key, answer in [("15/09/2026", "Ngày 2026-09-15."), ("5/9", "Ngày 05/09/2026."),
                            ("18.200 km", "Mốc 18200 km."), ("8:30", "Lúc 8 giờ 30."),
                            ("2027", "Hạn 2027-03-01."), ("18", "Lúc 18:30.")]:
            with self.subTest(key=key):
                self.assertTrue(evaluate.key_present(key, answer))


if __name__ == "__main__":
    unittest.main()
