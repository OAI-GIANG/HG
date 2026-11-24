"""Synthetic AC-A6 regressions. Fixtures are separate from acceptance holdouts."""
from hg.assistant import grounding
from hg.tests.test_assistant_ask import AskBase, FakeModel


class VietnameseEvidenceRegressionTests(AskBase):
    def test_event_location_question_retrieves_same_event(self):
        source, _ = self.nb.add("Buổi hòa nhạc Sao Mai tại sân Bạch Đàn.",
                                subject="recital", origin="test")
        self.nb.add("Buổi tập Sao Mai diễn ra ở sân Dẻ Gai.", subject="rehearsal", origin="test")
        model = FakeModel("Buổi hòa nhạc Sao Mai tại sân Bạch Đàn [N1].")

        _, receipt = self.run_ask("Buổi hòa nhạc Sao Mai diễn ra ở đâu?", model)

        self.assertEqual(receipt["outcome"], "ANSWERED")
        self.assertEqual([note["memory_id"] for note in receipt["notes"]], [source["memory_id"]])
        self.assertEqual(receipt["sentences"][0]["label"], "NOTE")

    def test_event_date_question_retrieves_same_event(self):
        self.nb.add("Lễ gắn biển Gốm Sứ vào ngày 19/08.", subject="ceremony", origin="test")
        model = FakeModel("Lễ gắn biển Gốm Sứ vào ngày 19/08 [N1].")

        _, receipt = self.run_ask("Lễ gắn biển Gốm Sứ diễn ra khi nào?", model)

        self.assertEqual(receipt["outcome"], "ANSWERED")
        self.assertEqual(receipt["sentences"][0]["label"], "NOTE")

    def test_event_date_cannot_cite_a_replaced_date_as_current(self):
        question = "Lễ gắn biển Gốm Sứ diễn ra khi nào?"
        for punctuation in (",", ""):
            note = f"Lễ gắn biển Gốm Sứ vào ngày 19/08{punctuation} thay cho ngày 18/08."
            good = grounding.check_sentence("Lễ gắn biển Gốm Sứ vào ngày 19/08 [N1].", {"N1": note},
                                            question=question)
            wrong = grounding.check_sentence("Lễ gắn biển Gốm Sứ vào ngày 18/08 [N1].", {"N1": note},
                                             question=question)
            self.assertEqual(good["label"], "NOTE")
            self.assertNotEqual(wrong["label"], "NOTE")
        pending = "Lễ gắn biển Gốm Sứ vào ngày 19/08 hoặc 20/08."
        self.assertIsNotNone(grounding.anchored(question, pending))

    def test_event_frame_does_not_license_other_events_or_unrelated_locations(self):
        for source in (
            "Buổi tập Sao Mai tại sân Dẻ Gai.",
            "Buổi hòa nhạc Hồng Loan tại sân Bạch Đàn.",
            "Buổi hòa nhạc Sao Mai bị hủy. Buổi tập Sao Mai tại sân Dẻ Gai.",
            "Buổi hòa nhạc Sao Mai bị hủy tại sân Dẻ Gai.",
            "Buổi hòa nhạc Sao Mai tại sao bị hủy?",
            "Buổi hòa nhạc Sao Mai tại sân Dẻ Gai?",
            "Buổi hòa nhạc Sao Mai không ở sân Dẻ Gai.",
            "Buổi hòa nhạc Sao Mai tại sân Bạch Đàn hoặc sân Dẻ Gai.",
        ):
            with self.subTest(source=source):
                self.assertIsNotNone(grounding.anchored("Buổi hòa nhạc Sao Mai diễn ra ở đâu?", source))

    def test_event_value_must_come_from_the_event_clause(self):
        question = "Buổi hòa nhạc Sao Mai diễn ra ở đâu?"
        for source in (
            "Buổi hòa nhạc Sao Mai tại sân Bạch Đàn. Buổi tập tại sân Dẻ Gai.",
            "Buổi hòa nhạc Sao Mai tại sân Bạch Đàn, buổi tập tại sân Dẻ Gai.",
            "Buổi hòa nhạc Sao Mai tại sân Bạch Đàn đối diện sân Dẻ Gai.",
        ):
            with self.subTest(source=source):
                good = grounding.check_sentence("Tại sân Bạch Đàn [N1].", {"N1": source}, question=question)
                bad = grounding.check_sentence("Tại sân Dẻ Gai [N1].", {"N1": source}, question=question)
                self.assertEqual(good["label"], "NOTE")
                self.assertNotEqual(bad["label"], "NOTE")

        source = {"N1": "Buổi hòa nhạc Sao Mai tại sân Bạch Đàn Nhỏ."}
        incomplete = grounding.check_sentence("Tại sân Bạch Đàn [N1].", source, question=question)
        self.assertNotEqual(incomplete["label"], "NOTE")

    def test_binary_question_with_machine_is_not_a_quantity_slot(self):
        self.nb.add("Máy khắc Rạng Đông chưa nghiệm thu.", subject="engraver", origin="test")
        model = FakeModel("Máy khắc Rạng Đông chưa nghiệm thu [N1].")

        _, receipt = self.run_ask("Máy khắc Rạng Đông đã nghiệm thu chưa?", model)

        self.assertEqual(receipt["sentences"][0]["label"], "NOTE")
        self.assertIsNone(receipt["retraction"])

    def test_affirmative_binary_answer_supplies_polarity_but_echo_does_not(self):
        question = "Máy khắc Rạng Đông đã nghiệm thu chưa?"
        source = {"N1": "Máy khắc Rạng Đông đã nghiệm thu."}
        result = grounding.check_sentence("Máy khắc Rạng Đông đã nghiệm thu [N1].", source, question=question)
        self.assertEqual(result["label"], "NOTE")
        self.assertEqual(grounding.check_sentence(question, source, question=question)["label"], "NONE")
        scheduled = {"N1": "Máy khắc Rạng Đông sẽ nghiệm thu."}
        result = grounding.check_sentence("Máy khắc Rạng Đông đã nghiệm thu [N1].", scheduled, question=question)
        self.assertNotEqual(result["label"], "NOTE")
        self.assertNotIn("number", grounding.answer_slots("Co may khac Rang Dong trong xuong khong?"))

    def test_quantity_question_with_machine_still_requires_a_quantity(self):
        for question in ("Máy đột có mấy khuôn?", "May dot co may khuon?", "Mã khuôn là số mấy?",
                         "Lop dan hoc may buoi?"):
            with self.subTest(question=question):
                self.assertIn("number", grounding.answer_slots(question))
                self.assertEqual(grounding.slot_mismatch("Máy đột có khuôn dự phòng.", ("number",)), ["number"])

    def test_list_conjunction_preserves_the_exact_grounded_items(self):
        question = "Bộ dụng cụ len gồm gì?"
        source = {"N1": "Bộ dụng cụ len gồm kim móc và sợi gai."}
        result = grounding.check_sentence("Bộ dụng cụ len gồm kim móc cùng với sợi gai [N1].",
                                          source, question=question)
        self.assertEqual((result["label"], result["note"]), ("NOTE", "N1"))

    def test_redundant_list_conjunction_is_grounded_without_other_word_exceptions(self):
        question = "Bộ bút vẽ gồm gì?"
        source = {"N1": "Bộ bút vẽ gồm bút và cọ."}
        reply = "Bộ bút vẽ gồm bút cùng cọ [N1]."
        self.assertEqual(grounding.check_sentence(reply, source, question=question)["label"], "NOTE")
        reply = "Bộ bút vẽ gồm bút cùng mực [N1]."
        self.assertNotEqual(grounding.check_sentence(reply, source, question=question)["label"], "NOTE")

    def test_conjunction_does_not_license_new_items_or_joint_action(self):
        samples = (
            ("Bộ dụng cụ len gồm gì?", "Bộ dụng cụ len gồm kim móc hoặc sợi gai.",
             "Bộ dụng cụ len gồm kim móc cùng với sợi gai [N1]."),
            ("Bộ dụng cụ len gồm gì?", "Bộ dụng cụ len gồm kim móc và sợi gai.",
             "Bộ dụng cụ len gồm kim móc cùng với sợi tơ [N1]."),
            ("Nhóm Mây chỉnh đàn với ai?", "Nhóm Mây chỉnh đàn. Đội Gió tới sau.",
             "Nhóm Mây chỉnh đàn cùng với đội Gió [N1]."),
        )
        for question, source, reply in samples:
            with self.subTest(reply=reply):
                result = grounding.check_sentence(reply, {"N1": source}, question=question)
                self.assertNotEqual(result["label"], "NOTE")

    def test_wrong_event_person_date_amount_and_polarity_cannot_get_note(self):
        cases = (
            ("Ai trực quầy Tầm Xuân?", "Lan trực quầy Tầm Xuân.",
             "Thu trực quầy Tầm Xuân."),
            ("Lễ gắn biển Gốm Sứ ngày nào?", "Lễ gắn biển Gốm Sứ vào ngày 19/08.",
             "Lễ gắn biển Gốm Sứ vào ngày 18/08."),
            ("Phí mài kéo tháng 8 là bao nhiêu?", "Phí mài kéo tháng 8 là 82.000 đồng.",
             "Phí mài kéo tháng 8 là 28.000 đồng."),
            ("Máy khắc Rạng Đông đã nghiệm thu chưa?", "Máy khắc Rạng Đông chưa nghiệm thu.",
             "Máy khắc Rạng Đông đã nghiệm thu."),
            ("Máy khắc Rạng Đông đã nghiệm thu chưa?", "Máy khắc Rạng Đông đã nghiệm thu.",
             "Máy khắc Rạng Đông chưa nghiệm thu."),
            ("Buổi hòa nhạc Sao Mai diễn ra ở đâu?", "Buổi hòa nhạc Sao Mai tại sân Bạch Đàn.",
             "Buổi tập Sao Mai tại sân Bạch Đàn."),
        )
        for question, source, reply in cases:
            with self.subTest(reply=reply):
                result = grounding.check_sentence(f"{reply} [N1]", {"N1": source}, question=question)
                self.assertNotEqual(result["label"], "NOTE")
