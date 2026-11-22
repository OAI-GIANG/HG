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

    def test_discriminative_name_must_match_the_specific_note(self):
        bin_note = "Giày thể thao của bé Bin cỡ 31, mua ở tiệm đầu đường Nguyễn Trãi."
        na_note = "Giày thể thao của bé Na cỡ 28, mua ở tiệm đầu đường Nguyễn Trãi."
        self.assertIsNotNone(grounding.anchored("Giày của bé Na cỡ mấy?", bin_note,
                                                other_notes=[na_note]))
        self.assertIsNone(grounding.anchored("Giày của bé Na cỡ mấy?", na_note,
                                             other_notes=[bin_note]))

    def test_discriminative_month_number_must_match(self):
        september = "Phí quản lý chung cư tháng 9 là 620.000 đồng."
        october = "Phí quản lý chung cư tháng 10 là 650.000 đồng."
        self.assertIsNotNone(grounding.anchored("Phí quản lý tháng 10 là bao nhiêu?", september,
                                                other_notes=[october]))
        self.assertIsNone(grounding.anchored("Phí quản lý tháng 10 là bao nhiêu?", october,
                                             other_notes=[september]))

    def test_answer_slot_requires_the_right_kind_of_value(self):
        note = {"N1": "Phí quản lý chung cư tháng 10 là 650.000 đồng."}
        good = grounding.check_sentence("Phí quản lý là 650.000 đồng [N1].", note,
                                        question="Phí quản lý tháng 10 là bao nhiêu tiền?")
        bad = grounding.check_sentence("Phí quản lý là quầy lễ tân tầng trệt [N1].", note,
                                       question="Phí quản lý tháng 10 là bao nhiêu tiền?")
        self.assertEqual(good["label"], "NOTE")
        self.assertEqual(bad["label"], "BADCITE")
        self.assertIn("price", " ".join(bad["reasons"]))
        # "Phí ... bao nhiêu?" is a monetary slot even when the question omits the word "tiền".
        no_currency = grounding.check_sentence("Phí quản lý là 650.000 [N1].", note,
                                                question="Phí quản lý tháng 10 là bao nhiêu?")
        self.assertEqual(no_currency["label"], "BADCITE")

    def test_time_date_person_and_place_slots_are_checked(self):
        note = {"N1": "Hẹn cắt tóc cho bé Bin ở tiệm Tóc Mây, thợ Long, ngày 2026-11-21 lúc 9 giờ."}
        self.assertEqual(grounding.check_sentence("Bé Bin hẹn ngày 2026-11-21 [N1].", note,
                          question="Bé Bin hẹn ngày nào?")["label"], "NOTE")
        self.assertEqual(grounding.check_sentence("Bé Bin hẹn lúc 9 giờ [N1].", note,
                          question="Bé Bin hẹn mấy giờ?")["label"], "NOTE")
        self.assertEqual(grounding.check_sentence("Thợ là Long [N1].", note,
                          question="Thợ cắt tóc tên gì?")["label"], "NOTE")
        self.assertEqual(grounding.check_sentence("Hẹn ở tiệm Tóc Mây [N1].", note,
                          question="Hẹn cắt tóc ở đâu?")["label"], "NOTE")
        wrong = grounding.check_sentence("Bé Bin hẹn tại tiệm Tóc Mây [N1].", note,
                          question="Bé Bin hẹn ngày nào?")
        self.assertEqual(wrong["label"], "BADCITE")

    def test_location_preposition_is_a_place_answer(self):
        note = {"N1": "Chìa khóa cổng để dưới chậu hoa giấy."}
        r = grounding.check_sentence("Chìa khóa cổng để dưới chậu hoa giấy [N1].", note,
                                     question="Chìa khóa cổng để ở đâu?")
        self.assertEqual(r["label"], "NOTE")

    def test_repeated_question_is_not_a_claim(self):
        r = grounding.check_sentence("Ăn cay?", {}, question="Ăn cay có được không?")
        self.assertEqual(r["label"], "NONE")


class V4FailureRootCauseTests(unittest.TestCase):
    """AC-A6 v4 FAIL (2026-11-22, bc54040, ledger section 75): 14 answerable questions were abstained.

    RC-1: the discriminative anchor treated question words ("bao" of "bao nhiêu", "tiền", "hết", "cỡ")
    as topic, and "bao" folds onto "bảo" in sibling notes, so the right note was rejected.
    RC-2: "ngày D tháng M" was not the same date as "D/M"; one- or two-digit keys kept their leading
    zero ("09" != "9"). RC-4: discourse markers ("cụ thể", "chính xác", "đúng không") counted as topic.
    Cases here are new examples, not v4 items."""

    def test_question_words_are_not_discriminative_terms(self):
        note = "Phí gửi xe tháng 10 là 150.000 đồng."
        siblings = ["Bảo hiểm xe máy hết hạn tháng 3.", "Tiền chợ tuần này hết 900.000 đồng."]
        for q in ("Phí gửi xe tháng 10 bao nhiêu tiền?", "Phi gui xe thang 10 het bao nhieu tien?",
                  "Phí gửi xe tháng 10 là bao nhiêu?"):
            with self.subTest(q=q):
                self.assertIsNone(grounding.anchored(q, note, other_notes=siblings))

    def test_size_question_with_sibling_still_discriminates_the_person(self):
        bin_note = "Áo khoác của bé Bin cỡ 120, mua ở chợ Bến Thành."
        na_note = "Áo khoác của bé Na cỡ 110, mua ở chợ Bến Thành."
        q = "Áo khoác của bé Na cỡ bao nhiêu?"
        self.assertIsNone(grounding.anchored(q, na_note, other_notes=[bin_note]))
        self.assertIsNotNone(grounding.anchored(q, bin_note, other_notes=[na_note]))

    def test_full_vietnamese_date_is_the_same_date_as_day_slash_month(self):
        self.assertEqual(textvi.numbers("ngày 3 tháng 7"), {"--07-03"})
        self.assertEqual(textvi.numbers("Ngay 3 thang 7 nam 2027"), {"2027-07-03"})
        self.assertEqual(textvi.number_gap("tiêm ngày 3 tháng 7", "Bé tiêm phòng lúc 8 giờ ngày 03/07."), set())
        self.assertEqual(textvi.number_gap("ngày 3 tháng 8", "ngày 03/07"), {"--08-03"})
        self.assertIsNone(grounding.anchored("Bé tiêm phòng ngày 3 tháng 7 lúc mấy giờ?",
                                             "Bé tiêm phòng lúc 8 giờ ngày 03/07 tại trạm y tế phường."))

    def test_one_or_two_digit_keys_ignore_a_leading_zero_but_identifiers_do_not(self):
        self.assertEqual(textvi.query_keys("tháng 8"), textvi.query_keys("tháng 08"))
        self.assertIn("~8", textvi.document_keys("Tiền nước tháng 08 là 120.000 đồng."))
        self.assertIsNone(grounding.anchored("Tiền nước tháng 8 là bao nhiêu?", "Tiền nước tháng 08 là 120.000 đồng."))
        self.assertNotEqual(textvi.query_keys("mã 0420"), textvi.query_keys("mã 420"))

    def test_discourse_markers_are_not_topic(self):
        keys = textvi.topic_keys("Hẹn nha sĩ ngày 9 tháng 12 đúng không, cụ thể là mấy giờ?")
        for k in ("đúng", "cụ", "thể", "ngày", "tháng"):
            self.assertNotIn(k, keys)
        self.assertIn("~9", keys)
        self.assertNotIn("chính", textvi.topic_keys("Chính xác thì mật khẩu wifi nhà là gì?"))
        # "cụ" alone is a person (great-grandparent) and stays a topic word.
        self.assertIn("cụ", textvi.topic_keys("Sinh nhật cụ nội là ngày nào?"))

    def test_kin_named_in_the_question_must_be_in_the_note(self):
        """RC-5 (v4 u07): a note about one relative never answers for another (false NOTE)."""
        ong_noi = "Ngày giỗ ông nội là 15/7 âm lịch."
        ba_ngoai = "Ngày giỗ bà ngoại là 3/2 âm lịch."
        q = "Ngày giỗ bà ngoại là ngày nào?"
        self.assertIsNotNone(grounding.anchored(q, ong_noi))
        self.assertIsNone(grounding.anchored(q, ba_ngoai, other_notes=[ong_noi]))
        self.assertIsNotNone(grounding.anchored("Sinh nhật ông ngoại là ngày nào?", "Sinh nhật bố là ngày 14/8."))
        wrong = grounding.check_sentence("Giỗ bà ngoại là ngày 15/7 âm lịch [N1].", {"N1": ong_noi}, question=q)
        self.assertNotEqual(wrong["label"], "NOTE")
        # Common synonyms on the note side still match: "má" is "mẹ", "ba"/"cha" are "bố".
        self.assertIsNone(grounding.anchored("Số điện thoại của mẹ là gì?", "Số điện thoại của má là 0912 345 678."))
        self.assertIsNone(grounding.anchored("Bố uống thuốc huyết áp lúc mấy giờ?", "Ba uống thuốc huyết áp lúc 7 giờ sáng."))
        # "ông"/"bà" as a pronoun or title is not a kin requirement.
        self.assertIsNone(grounding.anchored("Ông Tư hàng xóm số điện thoại là gì?",
                                             "Số điện thoại ông Tư hàng xóm là 0903 111 222."))

class V5FailureRootCauseTests(unittest.TestCase):
    """AC-A6 v5 FAIL (2026-11-22, 9f32f4c, ledger section 76). New examples, not v5 items.

    RC-6 (not fixed, by choice): a topic word shared with a sibling note rejects the right note when the
    note uses a synonym ("xe" vs "ô tô Vios"; "sinh nhật" vs "Bố sinh ngày ..."). Relaxing it let
    unanswerable near-misses through, so the strict rule stays (fail closed).
    RC-7: unaccented sentence-final particles and "may" (mấy) counted as topic ("ngay may vay").
    RC-8: a written time ("8h30") counted as a topic word although numbers() already compares it.
    RC-9: search needed half of ALL content words, so fillers ("cho mình hỏi", "nhỉ", "bao nhiêu")
    pushed the right note out of the candidates."""

    def test_near_miss_notes_stay_rejected_for_unanswerable_questions(self):
        """Safety over recall: a note that lacks the asked predicate, which a sibling has, is rejected
        (accented and unaccented). A relaxation tried for v5 RC-6 let these through and was reverted."""
        electricity = "Tiền điện tháng 10 là 650.000 đồng."
        water9 = "Tiền nước tháng 9 là 160.000 đồng."
        for q in ("Tiền nước tháng 10 là bao nhiêu?", "tien nuoc thang 10 het bao nhieu"):
            with self.subTest(q=q):
                self.assertIsNotNone(grounding.anchored(q, electricity, other_notes=[water9]))
        piano = "Bé Na học piano lúc 17 giờ thứ Ba."
        pool = "Hồ bơi chung cư mở cửa từ 6 giờ sáng."
        self.assertIsNotNone(grounding.anchored("Bé Na học bơi lúc mấy giờ?", piano, other_notes=[pool]))

    def test_a_dominating_sibling_still_rejects_the_candidate(self):
        bin_note = "Mũ bảo hiểm của bé Bin màu xanh, cỡ S."
        na_note = "Mũ bảo hiểm của bé Na màu đỏ, cỡ M."
        q = "mu bao hiem cua be na co gi"
        self.assertIsNotNone(grounding.anchored(q, bin_note, other_notes=[na_note]))
        self.assertIsNone(grounding.anchored(q, na_note, other_notes=[bin_note]))

    def test_unaccented_final_particles_and_may_are_not_topic(self):
        keys = textvi.topic_keys("cho Vang di tiem ngay may vay")
        for k in ("~may", "~vay"):
            self.assertNotIn(k, keys)
        self.assertNotIn("~nhi", textvi.topic_keys("hop phu huynh luc may gio nhi"))
        # "vay" inside a question is the topic word "vay" (loan), not a particle.
        self.assertIn("~vay", textvi.topic_keys("khoan vay ngan hang con bao nhieu"))
        # "may" naming a machine stays topic.
        self.assertIn("~may", textvi.topic_keys("may giat bao hanh den khi nao"))

    def test_written_time_is_not_a_topic_word(self):
        self.assertNotIn("~9h15", textvi.topic_keys("Cuộc hẹn 9h15 sáng thứ Sáu là gì?"))
        self.assertIsNone(grounding.anchored("Lịch 9h15 sáng thứ Sáu là việc gì?",
                                             "Lịch nha sĩ lúc 9 giờ 15 sáng thứ Sáu ở phòng khám Ánh Dương."))

    def test_filler_phrases_are_not_topic(self):
        keys = textvi.topic_keys("Cho mình hỏi tiền gas tháng 07 là bao nhiêu nhỉ?")
        for k in ("~cho", "hỏi", "nhỉ"):
            self.assertNotIn(k, keys)
        self.assertIn("~7", keys)

class V6FailureRootCauseTests(unittest.TestCase):
    """AC-A6 v6 FAIL (2026-11-22, 2f285c0, ledger section 77). New examples, not v6 items.

    RC-10 (safety): "tháng 10" was matched by "ngày 10" in a note about another month.
    RC-12 (safety): a capitalised name that is also a stopword ("Bi" ~ "bị") was never checked.
    RC-13: light words ("đi", "bắt đầu"), the slot "số" of "số mấy" and "giờ"/"phút" after a number
    counted as topic and rejected the right note.
    RC-14 (safety): one missing topic word was tolerated, so "khám răng" anchored a note about
    "khám mắt" and HG labelled the substituted answer NOTE."""

    def test_month_number_is_not_a_day_number(self):
        note = "Tiền gửi xe tháng 9 là 180.000 đồng, nộp trước ngày 10."
        self.assertTrue(textvi.number_gap("tháng 10", note))
        self.assertIsNotNone(grounding.anchored("Tiền gửi xe tháng 10 là bao nhiêu?", note))
        self.assertEqual(textvi.number_gap("tháng 10", "Hạn nộp là ngày 05/10/2026."), set())
        self.assertEqual(textvi.number_gap("tháng 9", note), set())
        # eval keys (parts=True): a plain "9" key is still found in "tháng 9"
        self.assertEqual(textvi.number_gap("9", "tháng 9", parts=True), set())

    def test_every_capitalised_name_must_be_in_the_note(self):
        na = "Lớp học vẽ của bé Na vào 15 giờ thứ Tư."
        self.assertIsNotNone(grounding.anchored("Lớp học vẽ của bé Bi vào lúc mấy giờ?", na))
        bi = "Lớp học vẽ của bé Bi vào 16 giờ thứ Năm."
        self.assertIsNone(grounding.anchored("Lớp học vẽ của bé Bi vào lúc mấy giờ?", bi, other_notes=[na]))

    def test_light_words_and_time_units_are_not_topic(self):
        keys = textvi.topic_keys("Ông nội đi tái khám bắt đầu lúc 9 giờ 30 phút phải không?")
        for k in ("đi", "bắt", "đầu", "giờ", "phút"):
            self.assertNotIn(k, keys)
        self.assertNotIn("số", textvi.topic_keys("Mã tủ khóa ở phòng gym là số mấy?"))
        self.assertIsNone(grounding.anchored("Mã tủ khóa ở phòng gym là số mấy?", "Mã tủ khóa phòng gym: 5521."))
        self.assertIsNone(grounding.anchored("Bà nội đi đo đường huyết lúc mấy giờ?",
                                             "Bà nội đo đường huyết lúc 6 giờ sáng.",
                                             other_notes=["Bố đi công tác Đà Nẵng ngày 3/12."]))

    def test_no_missing_topic_word_is_tolerated(self):
        eye = "Mẹ hẹn khám mắt lúc 9 giờ sáng thứ Hai tại phòng khám Ánh Sáng."
        self.assertIsNotNone(grounding.anchored("Mẹ hẹn khám răng vào ngày nào?", eye))
        wrong = grounding.check_sentence("Mẹ hẹn khám răng lúc 9 giờ sáng thứ Hai [N1].", {"N1": eye},
                                         question="Mẹ hẹn khám răng vào ngày nào?")
        self.assertNotEqual(wrong["label"], "NOTE")
        self.assertIsNone(grounding.anchored("Mẹ hẹn khám mắt vào ngày nào?", eye))

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
