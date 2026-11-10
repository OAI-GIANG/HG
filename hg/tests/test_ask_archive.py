import tempfile
import unittest
from pathlib import Path

from hg.assistant.ask import append_receipt
from hg.assistant.ask_archive import (
    AskArchiveError, preview_model_derived_save, save_model_derived_content,
)
from hg.assistant.notes import Notebook


class AskArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-ask-archive-"))
        self.home = self.tmp / "assistant"
        self.home.mkdir(mode=0o700)
        self.clock_value = None
        self.event = append_receipt(
            self.home, "ASK",
            {
                "outcome": "ANSWERED",
                "question": "Tôi nên bảo dưỡng xe thế nào?",
                "answer": "Nên kiểm tra dầu máy định kỳ và ghi lại số km mỗi lần thay.",
                "provider": "ollama",
                "model": "local-fixture",
                "channel": "http:/v1/chat",
            },
            clock=lambda: __import__("datetime").datetime(2026, 11, 1, tzinfo=__import__("datetime").timezone.utc),
        )
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def preview(self, text=None):
        if text is None:
            text = self.event["payload"]["answer"]
        return preview_model_derived_save(
            self.home, self.event["event_id"], subject="bao-duong-xe", text=text
        )

    def test_preview_is_read_only_and_digest_bound(self):
        report = self.preview()
        self.assertFalse(report["will_write"])
        self.assertEqual(report["receipt_event_id"], self.event["event_id"])
        self.assertEqual(len(report["confirmation_sha256"]), 64)
        self.assertFalse((self.home / "notes.jsonl").exists())

    def test_wrong_digest_writes_nothing(self):
        report = self.preview()
        with self.assertRaisesRegex(AskArchiveError, "digest mismatch"):
            save_model_derived_content(
                self.home, self.event["event_id"], subject="bao-duong-xe",
                text=report["content"], confirm_sha256="0" * 64,
            )
        self.assertFalse((self.home / "notes.jsonl").exists())

    def test_confirmed_restatement_preserves_source_link_and_owner_status(self):
        report = self.preview()
        note, created = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"],
        )
        self.assertTrue(created)
        self.assertEqual((note["kind"], note["source"], note["layer"]), ("NOTE", "USER", "SEMANTIC"))
        self.assertIn(self.event["event_id"], note["source_ref"])
        self.assertIn(report["confirmation_sha256"], note["source_ref"])
        self.assertEqual(note["content_origin"], "MODEL_DERIVED")
        self.assertEqual(note["authorized_by"], "OWNER")
        self.assertIs(note["owner_confirmed"], True)
        self.assertEqual(note["ask_receipt_id"], self.event["event_id"])
        self.assertNotIn("verified_truth", note)

    def test_retry_is_idempotent_even_after_process_reconstruction(self):
        report = self.preview()
        first, created = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"],
        )
        second, created_again = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"],
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(len(Notebook(self.home).snapshot()), 1)

    def test_verbatim_model_answer_can_be_saved_only_as_model_derived_after_confirmation(self):
        text = self.event["payload"]["answer"]
        report = preview_model_derived_save(self.home, self.event["event_id"],
                                           subject="bao-duong-xe", text=text)
        self.assertFalse(report["will_write"])
        note, created = save_model_derived_content(
            self.home, self.event["event_id"], subject="bao-duong-xe", text=text,
            confirm_sha256=report["confirmation_sha256"])
        self.assertTrue(created)
        self.assertEqual(note["content_origin"], "MODEL_DERIVED")
        self.assertEqual(note["authorized_by"], "OWNER")
        self.assertIs(note["owner_confirmed"], True)
        self.assertEqual(note["source"], "USER")


    def test_source_ref_retry_requires_exact_content_not_case_or_whitespace_equivalence(self):
        from hg.assistant.notes import NoteError

        report = self.preview()
        note, _ = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"])
        altered = report["content"].replace(" ", "  ", 1)
        with self.assertRaises(NoteError):
            Notebook(self.home).add(
                altered, subject=report["subject"], origin="test", source_ref=note["source_ref"],
                ask_receipt_id=note["ask_receipt_id"], content_origin=note["content_origin"],
                authorized_by=note["authorized_by"], owner_confirmed=note["owner_confirmed"],
                model_output_sha256=note["model_output_sha256"],
                model_output_start=note["model_output_start"], model_output_end=note["model_output_end"],
                save_confirmation_sha256=note["save_confirmation_sha256"])

    def test_new_ask_receipt_cannot_claim_existing_note_with_old_provenance(self):
        from datetime import datetime, timezone
        from hg.assistant.notes import NoteConflict

        report = self.preview()
        first, created = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"])
        self.assertTrue(created)

        new_event = append_receipt(self.home, "ASK", {
            "outcome": "ANSWERED", "question": "Có thể xác nhận lại nội dung không?",
            "answer": self.event["payload"]["answer"],
            "provider": "ollama", "model": "local-fixture", "channel": "http:/v1/chat"},
            clock=lambda: datetime(2026, 11, 1, 2, tzinfo=timezone.utc))
        new_preview = preview_model_derived_save(
            self.home, new_event["event_id"], subject=report["subject"], text=report["content"])
        with self.assertRaises(NoteConflict):
            save_model_derived_content(
                self.home, new_event["event_id"], subject=report["subject"],
                text=report["content"], confirm_sha256=new_preview["confirmation_sha256"])

        active = Notebook(self.home).active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["memory_id"], first["memory_id"])
        self.assertEqual(active[0]["ask_receipt_id"], self.event["event_id"])
        self.assertNotEqual(active[0]["ask_receipt_id"], new_event["event_id"])

    def test_retry_after_forget_is_rejected_as_inactive(self):
        from hg.assistant.notes import NoteInactive
        report = self.preview()
        first, _ = save_model_derived_content(self.home, self.event["event_id"],
            subject=report["subject"], text=report["content"], confirm_sha256=report["confirmation_sha256"])
        Notebook(self.home).forget(first["memory_id"], reason="owner forget")
        with self.assertRaises(NoteInactive) as ctx:
            save_model_derived_content(self.home, self.event["event_id"],
                subject=report["subject"], text=report["content"], confirm_sha256=report["confirmation_sha256"])
        self.assertEqual(ctx.exception.record["status"], "RETRACTED")
        self.assertEqual(Notebook(self.home).active(), [])

    def test_new_ask_receipt_and_fresh_confirmation_can_save_after_retraction(self):
        report = self.preview()
        first, _ = save_model_derived_content(self.home, self.event["event_id"],
            subject=report["subject"], text=report["content"], confirm_sha256=report["confirmation_sha256"])
        Notebook(self.home).forget(first["memory_id"], reason="owner forget")
        from datetime import datetime, timezone
        new_event = append_receipt(self.home, "ASK", {
            "outcome": "ANSWERED", "question": "Cập nhật hướng dẫn bảo dưỡng?",
            "answer": "Hãy theo dõi lịch bảo dưỡng và số km vận hành.",
            "provider": "ollama", "model": "local-fixture", "channel": "http:/v1/chat"},
            clock=lambda: datetime(2026, 11, 1, 1, tzinfo=timezone.utc))
        new_text = new_event["payload"]["answer"]
        new_preview = preview_model_derived_save(self.home, new_event["event_id"],
            subject=report["subject"], text=new_text)
        self.assertNotEqual(new_preview["confirmation_sha256"], report["confirmation_sha256"])
        second, created = save_model_derived_content(self.home, new_event["event_id"],
            subject=report["subject"], text=new_text,
            confirm_sha256=new_preview["confirmation_sha256"])
        self.assertTrue(created)
        self.assertNotEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(second["status"], "ACTIVE")
        self.assertEqual(second["ask_receipt_id"], new_event["event_id"])
        self.assertEqual(len(Notebook(self.home).active()), 1)

    def test_retry_after_supersede_is_rejected_as_inactive(self):
        from hg.assistant.notes import NoteInactive
        report = self.preview()
        first, _ = save_model_derived_content(self.home, self.event["event_id"],
            subject=report["subject"], text=report["content"], confirm_sha256=report["confirmation_sha256"])
        Notebook(self.home).add("Nội dung cập nhật lịch bảo dưỡng xe.", subject=report["subject"],
                                replaces=first["memory_id"], origin="test")
        with self.assertRaises(NoteInactive):
            save_model_derived_content(self.home, self.event["event_id"],
                subject=report["subject"], text=report["content"], confirm_sha256=report["confirmation_sha256"])
        self.assertEqual(len(Notebook(self.home).active()), 1)

    def test_chat_service_maps_inactive_ask_save_to_http_409(self):
        from hg.chat import ChatService
        from hg.http_api import HTTPBoundaryError
        service = ChatService(self.home)
        text = self.event["payload"]["answer"]
        preview = service.preview_memory_save(
            self.event["event_id"], subject="bao-duong-xe", text=text)
        saved = service.save_model_derived_memory(
            self.event["event_id"], subject="bao-duong-xe", text=text,
            confirm_sha256=preview["confirmation_sha256"])
        self.assertEqual(saved["status"], "ACTIVE")
        Notebook(self.home).forget(saved["memory_id"], reason="owner forget")
        with self.assertRaises(HTTPBoundaryError) as ctx:
            service.save_model_derived_memory(
                self.event["event_id"], subject="bao-duong-xe", text=text,
                confirm_sha256=preview["confirmation_sha256"])
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "memory_save_inactive"))
        self.assertEqual(Notebook(self.home).active(), [])

    def test_non_answered_receipt_is_refused(self):
        event = append_receipt(
            self.home, "ASK", {"outcome": "NO_DATA", "answer": "Ghi chú chưa có thông tin."},
            clock=lambda: __import__("datetime").datetime(2026, 11, 1, tzinfo=__import__("datetime").timezone.utc),
        )
        with self.assertRaisesRegex(AskArchiveError, "only a completed ANSWERED"):
            preview_model_derived_save(
                self.home, event["event_id"], subject="test", text="Tôi chưa có thông tin này."
            )

    def test_missing_and_malformed_receipt_ids_are_refused(self):
        for bad in ("missing", "f" * 32):
            with self.assertRaises(AskArchiveError):
                preview_model_derived_save(self.home, bad, subject="test", text="Nội dung do tôi ghi.")

    def test_changed_content_invalidates_confirmation(self):
        report = self.preview()
        with self.assertRaisesRegex(AskArchiveError, "digest mismatch"):
            save_model_derived_content(
                self.home, self.event["event_id"], subject=report["subject"],
                text="ghi lại số km",
                confirm_sha256=report["confirmation_sha256"],
            )
        self.assertFalse((self.home / "notes.jsonl").exists())


    def test_owner_entered_text_cannot_be_saved_as_model_derived(self):
        from hg.chat import ChatService
        from hg.http_api import HTTPBoundaryError

        forged = "Nội dung do Chủ Nhân tự nhập, không xuất hiện trong câu trả lời model."
        with self.assertRaisesRegex(AskArchiveError, "exact excerpt"):
            self.preview(forged)
        service = ChatService(self.home)
        with self.assertRaises(HTTPBoundaryError) as ctx:
            service.preview_memory_save(self.event["event_id"], subject="bao-duong-xe", text=forged)
        self.assertEqual(ctx.exception.status, 400)
        self.assertFalse((self.home / "notes.jsonl").exists())

    def test_same_receipt_cannot_be_rebound_after_retraction_to_changed_content_or_subject(self):
        from hg.assistant.notes import NoteError, NoteInactive
        report = self.preview()
        first, _ = save_model_derived_content(self.home, self.event["event_id"],
            subject=report["subject"], text=report["content"], confirm_sha256=report["confirmation_sha256"])
        Notebook(self.home).forget(first["memory_id"], reason="owner forget")

        # Exact replay remains inactive; a fresh preview for another valid excerpt of the
        # same model answer must not consume the old receipt a second time.
        with self.assertRaises(NoteInactive):
            save_model_derived_content(self.home, self.event["event_id"],
                subject=report["subject"], text=report["content"],
                confirm_sha256=report["confirmation_sha256"])
        changed_text = "ghi lại số km"
        changed = self.preview(changed_text)
        with self.assertRaises(NoteError):
            save_model_derived_content(self.home, self.event["event_id"],
                subject=report["subject"], text=changed_text,
                confirm_sha256=changed["confirmation_sha256"])
        changed_subject = preview_model_derived_save(
            self.home, self.event["event_id"], subject="lich-bao-duong-moi", text=report["content"])
        with self.assertRaises(NoteError):
            save_model_derived_content(self.home, self.event["event_id"],
                subject="lich-bao-duong-moi", text=report["content"],
                confirm_sha256=changed_subject["confirmation_sha256"])
        self.assertEqual(len(Notebook(self.home).snapshot()), 1)
        self.assertEqual(Notebook(self.home).active(), [])

    def test_ask_receipt_cannot_be_replayed_without_explicit_subject(self):
        from maep.core import MAEPError
        report = self.preview()
        saved, _ = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"])
        with self.assertRaisesRegex(MAEPError, "explicit subject"):
            Notebook(self.home).add(
                saved["content"], origin="test", source_ref=saved["source_ref"],
                content_origin=saved["content_origin"], authorized_by=saved["authorized_by"],
                owner_confirmed=saved["owner_confirmed"], ask_receipt_id=saved["ask_receipt_id"],
                model_output_sha256=saved["model_output_sha256"],
                model_output_start=saved["model_output_start"], model_output_end=saved["model_output_end"],
                save_confirmation_sha256=saved["save_confirmation_sha256"])
        self.assertEqual(len(Notebook(self.home).snapshot()), 1)

    def test_same_receipt_replay_with_changed_provenance_origin_is_rejected(self):
        from hg.assistant.notes import NoteError
        report = self.preview()
        note, _ = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"])
        with self.assertRaises(NoteError):
            Notebook(self.home).add(
                note["content"], subject=note["subject"], origin="test",
                source_ref=note["source_ref"], content_origin="OWNER_AUTHORED",
                authorized_by="OWNER", owner_confirmed=True, ask_receipt_id=note["ask_receipt_id"],
                model_output_sha256=note["model_output_sha256"],
                model_output_start=note["model_output_start"], model_output_end=note["model_output_end"],
                save_confirmation_sha256=note["save_confirmation_sha256"])
        self.assertEqual(len(Notebook(self.home).snapshot()), 1)

    def test_concurrent_exact_replay_of_one_receipt_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        report = self.preview()
        def save_once(_):
            return save_model_derived_content(
                self.home, self.event["event_id"], subject=report["subject"],
                text=report["content"], confirm_sha256=report["confirmation_sha256"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(save_once, range(4)))
        self.assertEqual(len({record["memory_id"] for record, _ in results}), 1)
        self.assertEqual(sum(bool(created) for _, created in results), 1)
        self.assertEqual(len(Notebook(self.home).snapshot()), 1)

    def test_model_output_digest_mismatch_is_rejected_even_with_owner_confirmation(self):
        from maep.core import MAEPError
        report = self.preview()
        note, _ = save_model_derived_content(
            self.home, self.event["event_id"], subject=report["subject"],
            text=report["content"], confirm_sha256=report["confirmation_sha256"])
        with self.assertRaisesRegex(MAEPError, "different immutable save identity"):
            Notebook(self.home).add(
                note["content"], subject=note["subject"], origin="test",
                source_ref=note["source_ref"], content_origin=note["content_origin"],
                authorized_by=note["authorized_by"], owner_confirmed=note["owner_confirmed"],
                ask_receipt_id=note["ask_receipt_id"], model_output_sha256="f" * 64,
                model_output_start=note["model_output_start"], model_output_end=note["model_output_end"],
                save_confirmation_sha256=note["save_confirmation_sha256"])
        self.assertEqual(len(Notebook(self.home).snapshot()), 1)

    def test_direct_notebook_cannot_forge_model_derived_without_bound_receipt_proof(self):
        from maep.core import MAEPError
        with self.assertRaises(MAEPError):
            Notebook(self.home).add(
                self.event["payload"]["answer"], subject="bao-duong-xe", origin="test",
                source_ref="ask:" + self.event["event_id"] + ":forged",
                content_origin="MODEL_DERIVED", authorized_by="OWNER", owner_confirmed=True,
                ask_receipt_id=self.event["event_id"])
        self.assertEqual(Notebook(self.home).snapshot(), [])

    def test_confirmation_digest_is_bound_to_authenticated_owner_principal(self):
        text = self.event["payload"]["answer"]
        first = preview_model_derived_save(
            self.home, self.event["event_id"], subject="bao-duong-xe", text=text,
            principal_id="owner:test-principal-a")
        second = preview_model_derived_save(
            self.home, self.event["event_id"], subject="bao-duong-xe", text=text,
            principal_id="owner:test-principal-b")
        self.assertNotEqual(first["confirmation_sha256"], second["confirmation_sha256"])
        saved, created = save_model_derived_content(
            self.home, self.event["event_id"], subject="bao-duong-xe", text=text,
            confirm_sha256=first["confirmation_sha256"], principal_id="owner:test-principal-a")
        self.assertTrue(created)
        self.assertEqual(saved["authorized_principal_id"], "owner:test-principal-a")
        with self.assertRaisesRegex(AskArchiveError, "digest mismatch"):
            save_model_derived_content(
                self.home, self.event["event_id"], subject="bao-duong-xe", text=text,
                confirm_sha256=first["confirmation_sha256"], principal_id="owner:test-principal-b")
        self.assertEqual(len(Notebook(self.home).active()), 1)



if __name__ == "__main__":
    unittest.main(verbosity=2)
