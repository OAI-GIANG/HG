"""Vietnamese analysis and HG's sentence check (AC-A1, AC-A2, AC-A7, AC-N1 search part)."""
import unicodedata
import unittest

from hg.assistant import grounding, textvi

NOTES = {
    "N1": "Xe máy Honda Vision của tôi biển số 59X3-12345, thay dầu lần cuối ngày 2026-09-15 ở mốc 18.200 km.",
    "N2": "Họp nhóm dự án HG vào thứ Năm hằng tuần lúc 20 giờ, gọi qua Google Meet.",
    "N3": "Tôi không bị dị ứng tôm nhưng bị dị ứng đậu phộng.",
    "N4": "Ngân sách ăn uống mỗi tháng là 4 triệu đồng, không ăn ngoài quá 2 lần mỗi tuần.",
    "N5": "Lịch khám răng tiếp theo vào ngày 2026-11-20 lúc 9 giờ sáng tại nha khoa Minh Tâm.",
}


def label(sentence, notes=NOTES):
    return grounding.check_sentence(sentence, notes)


class TextAnalysisTests(unittest.TestCase):
    def test_folding_handles_d_with_stroke_and_marks(self):
        self.assertEqual(textvi.fold("Đường đến Đà Lạt"), "Duong den Da Lat")

    def test_function_syllables_are_dropped_but_negations_kept(self):
        self.assertEqual(textvi.content_words("Tôi là người không thích cà phê"), ["không", "thích", "cà", "phê"])

    def test_accented_word_matches_only_itself_unaccented_matches_all(self):
        self.assertIn("thủ", textvi.query_keys("thủ đô"))
        self.assertNotIn("thủ", textvi.document_keys("thứ Năm"))
        self.assertIn("~thu", textvi.query_keys("thu nam"))
        self.assertIn("~thu", textvi.document_keys("thứ Năm"))

    def test_nfd_input_equals_nfc(self):
        nfd = unicodedata.normalize("NFD", "Tiếng Việt không dấu")
        self.assertEqual(textvi.content_words(nfd), textvi.content_words("Tiếng Việt không dấu"))

    def test_numbers_compare_as_atoms(self):
        self.assertEqual(textvi.numbers("ngày 15/09/2026"), textvi.numbers("2026-09-15"))
        self.assertEqual(textvi.numbers("18.200 km"), {"18200"})
        self.assertEqual(textvi.numbers("1.250.000 đồng"), {"1250000"})


class SentenceCheckTests(unittest.TestCase):
    """AC-A1."""

    def test_supported_sentence_with_reformatted_date_is_note(self):
        r = label("Bạn thay dầu xe lần cuối vào ngày 15/09/2026 ở mốc 18.200 km [N1].")
        self.assertEqual((r["label"], r["note"]), ("NOTE", "N1"))

    def test_hg_finds_support_even_without_model_citation(self):
        self.assertEqual(label("Họp nhóm HG vào thứ Năm lúc 20 giờ qua Google Meet.")["label"], "NOTE")

    def test_names_that_are_also_function_words_are_found(self):
        notes = {"N1": "Lớp tiếng Anh tối thứ Hai và thứ Tư lúc 19 giờ ở trung tâm ILA Quận 3."}
        self.assertEqual(label("Lớp tiếng Anh học vào thứ Hai và thứ Tư.", notes)["label"], "NOTE")

    def test_unsupported_sentence_is_model(self):
        self.assertEqual(label("Paris là thủ đô của nước Pháp.")["label"], "MODEL")

    def test_citation_of_missing_note_is_badcite(self):
        r = label("Lốp xe đạp cần bơm 60 psi [N9].")
        self.assertEqual(r["label"], "BADCITE")
        self.assertIn("N9", r["reasons"][0])

    def test_wrong_citation_is_ignored_when_another_note_supports(self):
        r = label("Ngân sách ăn uống là 4 triệu đồng mỗi tháng [N2].")
        self.assertEqual((r["label"], r["note"]), ("NOTE", "N4"))
        self.assertTrue(r["reasons"])

    def test_filler_and_abstention_are_not_claims(self):
        self.assertEqual(label("Vâng.")["label"], "NONE")
        self.assertEqual(label("Ghi chú chưa có thông tin này.")["label"], "ABSTAIN")

    def test_citation_after_full_stop_stays_with_its_sentence(self):
        parts = grounding.split_sentences("Họp lúc 20 giờ. [N2] Khám răng ngày 2026-11-20 [N5].")
        self.assertEqual(parts, ["Họp lúc 20 giờ. [N2]", "Khám răng ngày 2026-11-20 [N5]."])


# AC-A2: fixed adversarial outputs. Each changes a number, date, name or negation of a note
# while copying most of its words. HG must never label any of them NOTE.
ADVERSARIAL = [
    "Bạn thay dầu xe lần cuối ngày 2026-09-16 ở mốc 18.200 km [N1].",
    "Bạn thay dầu xe lần cuối ngày 2026-09-15 ở mốc 19.200 km [N1].",
    "Xe máy Honda Vision biển số 59X3-12346 [N1].",
    "Xe máy Yamaha Vision thay dầu ngày 2026-09-15 [N1].",
    "Họp nhóm dự án HG vào thứ Năm lúc 21 giờ qua Google Meet [N2].",
    "Họp nhóm dự án HG vào thứ Năm lúc 20 giờ qua Zoom [N2].",
    "Họp nhóm dự án HG lúc 8 giờ qua Google Meet [N2].",
    "Bạn bị dị ứng tôm [N3].",
    "Bạn không bị dị ứng đậu phộng [N3].",
    "Bạn ko bị dị ứng đậu phộng.",
    "Bạn có thể ăn ngoài quá 2 lần mỗi tuần [N4].",
    "Ngân sách ăn uống mỗi tháng là 5 triệu đồng [N4].",
    "Ngân sách ăn uống mỗi tháng là 4 triệu đồng, ăn ngoài tối đa 3 lần mỗi tuần [N4].",
    "Lịch khám răng vào ngày 2026-11-21 lúc 9 giờ sáng [N5].",
    "Lịch khám răng vào ngày 2026-11-20 lúc 10 giờ sáng [N5].",
    "Khám răng tại nha khoa Kim Tâm ngày 2026-11-20 [N5].",
    "Khám răng tại nha khoa Minh Châu lúc 9 giờ [N5].",
    "Thay dầu lần cuối ngày 15/10/2026 [N1].",
    "Bạn không ăn ngoài, ngân sách ăn uống 4 triệu đồng mỗi ngày [N4].",
    "Họp nhóm dự án HG vào thứ Năm hằng tuần lúc 20 giờ 30 [N2].",
    "Bạn bị dị ứng tôm và đậu phộng.",
]


class AdversarialTests(unittest.TestCase):
    """AC-A2: zero NOTE labels on altered facts."""

    def test_no_altered_fact_is_labelled_note(self):
        self.assertGreaterEqual(len(ADVERSARIAL), 20)
        leaks = [(s, label(s)) for s in ADVERSARIAL if label(s)["label"] == "NOTE"]
        self.assertEqual(leaks, [], "altered facts accepted as supported")

    def test_correct_negations_are_still_supported(self):
        for s in ("Bạn không bị dị ứng tôm.", "Bạn ko bị dị ứng tôm.", "Bạn bị dị ứng đậu phộng.",
                  "Bạn không nên ăn ngoài quá 2 lần mỗi tuần."):
            self.assertEqual(label(s)["label"], "NOTE", s)


class NoteConflictTests(unittest.TestCase):
    """AC-A7."""

    def test_two_notes_disagreeing_on_a_number_are_reported(self):
        found = grounding.note_conflicts({"N1": "Họp nhóm HG thứ Năm lúc 20 giờ qua Google Meet.",
                                          "N2": "Họp nhóm HG thứ Năm lúc 21 giờ qua Google Meet.",
                                          "N3": "Cây lan tưới 2 lần mỗi tuần."})
        self.assertEqual([c["notes"] for c in found], [["N1", "N2"]])

    def test_unrelated_notes_are_not_conflicts(self):
        self.assertEqual(grounding.note_conflicts({"N1": NOTES["N2"], "N2": NOTES["N4"]}), [])


if __name__ == "__main__":
    unittest.main()
