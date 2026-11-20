import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from avatar_studio.store import Store, StudioError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name))
        self.addCleanup(self.store.close)
        self.owner = "default"
        self.project = self.store.create(self.owner, "First avatar")

    def asset(self, kind):
        path = self.store.media_dir / f"{uuid4()}.bin"
        path.write_bytes(f"approved {kind}".encode())
        return self.store.add_asset(self.owner, self.project["id"], kind, path, {"duration": 8})

    def approve(self, kind):
        asset = self.asset(kind)
        project = self.store.get(self.owner, self.project["id"])
        return self.store.approve(self.owner, project["id"], project["revision"], kind, asset["id"], asset["sha256"])

    def prepare(self):
        project = self.store.get(self.owner, self.project["id"])
        self.store.update(self.owner, project["id"], project["revision"], {"rights_confirmed": True})
        self.approve("image")
        self.approve("audio")

    def test_project_survives_reopening_the_store(self):
        other = Store(Path(self.folder.name))
        self.addCleanup(other.close)
        self.assertEqual(other.get(self.owner, self.project["id"])["title"], "First avatar")

    def test_another_owner_cannot_read_or_change_a_project(self):
        with self.assertRaises(StudioError) as caught:
            self.store.get("another-user", self.project["id"])
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.store.list("another-user"), [])

    def test_update_rejects_a_stale_revision(self):
        self.store.update(self.owner, self.project["id"], 0, {"script": "Hello"})
        with self.assertRaises(StudioError) as caught:
            self.store.update(self.owner, self.project["id"], 0, {"script": "Overwrite"})
        self.assertEqual(caught.exception.status, 409)

    def test_invalid_identifiers_and_unknown_fields_are_rejected(self):
        for identifier in ("../secret", "", "null"):
            with self.subTest(identifier=identifier), self.assertRaises(StudioError):
                self.store.get(self.owner, identifier)
        with self.assertRaises(StudioError):
            self.store.update(self.owner, self.project["id"], 0, {"approved_image": "forged"})

    def test_video_requires_both_approvals_but_ignores_legacy_permission_flag(self):
        self.store.update(self.owner, self.project["id"], 0, {"rights_confirmed": False})
        for stage in range(2):
            if stage == 1:
                self.approve("image")
            project = self.store.get(self.owner, self.project["id"])
            with self.assertRaises(StudioError):
                self.store.begin_job(self.owner, project["id"], project["revision"], "video", str(uuid4()))
        self.approve("audio")
        project = self.store.get(self.owner, self.project["id"])
        self.assertFalse(project["rights_confirmed"])
        _, created = self.store.begin_job(self.owner, project["id"], project["revision"], "video", str(uuid4()))
        self.assertTrue(created)

    def test_generation_field_edits_preserve_uploaded_candidates_and_approvals(self):
        for kind in ("image", "audio"):
            path = self.store.media_dir / f"{uuid4()}.bin"
            path.write_bytes(b"uploaded fixture")
            asset = self.store.add_asset(
                self.owner, self.project["id"], kind, path, {"origin": "upload", "duration": 8}
            )
            project = self.store.get(self.owner, self.project["id"])
            self.store.approve(self.owner, project["id"], project["revision"], kind, asset["id"], asset["sha256"])
        project = self.store.get(self.owner, self.project["id"])
        updated = self.store.update(
            self.owner,
            project["id"],
            project["revision"],
            {
                "script": "Optional generation text",
                "character_prompt": "Optional prompt",
                "ratio": "9:16",
            },
        )
        self.assertEqual(updated["current"], project["current"])
        self.assertEqual(updated["approvals"], project["approvals"])
        reference = self.store.media_dir / f"{uuid4()}.bin"
        reference.write_bytes(b"reference fixture")
        self.store.add_asset(self.owner, project["id"], "reference", reference, {})
        with_reference = self.store.get(self.owner, project["id"])
        self.assertEqual(with_reference["current"]["image"], project["current"]["image"])
        removed = self.store.remove_reference(self.owner, project["id"], with_reference["revision"])
        self.assertEqual(removed["approvals"]["image"], project["approvals"]["image"])

    def test_script_edit_invalidates_audio_but_preserves_portrait_approval(self):
        self.prepare()
        project = self.store.get(self.owner, self.project["id"])
        updated = self.store.update(self.owner, project["id"], project["revision"], {"script": "New words"})
        self.assertIsNone(updated["approvals"]["audio"])
        self.assertIsNotNone(updated["approvals"]["image"])
        with self.assertRaises(StudioError):
            self.store.begin_job(self.owner, updated["id"], updated["revision"], "video", str(uuid4()))

    def test_replacing_portrait_does_not_implicitly_approve_it(self):
        self.approve("image")
        self.asset("image")
        self.assertIsNone(self.store.get(self.owner, self.project["id"])["approvals"]["image"])

    def test_asset_bytes_changed_after_approval_block_video(self):
        self.prepare()
        project = self.store.get(self.owner, self.project["id"])
        asset = self.store.asset(self.owner, project["id"], project["current"]["audio"])
        self.store.asset_path(asset).write_bytes(b"changed after approval")
        with self.assertRaises(StudioError):
            self.store.begin_job(self.owner, project["id"], project["revision"], "video", str(uuid4()))

    def test_approval_rejects_wrong_hash_or_historical_asset(self):
        first = self.asset("image")
        self.asset("image")
        project = self.store.get(self.owner, self.project["id"])
        with self.assertRaises(StudioError):
            self.store.approve(self.owner, project["id"], project["revision"], "image", first["id"], first["sha256"])

    def test_duplicate_operation_returns_existing_job_without_second_submission(self):
        self.prepare()
        project = self.store.get(self.owner, self.project["id"])
        operation = str(uuid4())
        first, created = self.store.begin_job(self.owner, project["id"], project["revision"], "video", operation)
        second, recreated = self.store.begin_job(self.owner, project["id"], project["revision"], "video", operation)
        self.assertTrue(created)
        self.assertFalse(recreated)
        self.assertEqual(first["id"], second["id"])

    def test_concurrent_submissions_create_only_one_active_job(self):
        self.prepare()
        project = self.store.get(self.owner, self.project["id"])

        def submit(_):
            try:
                self.store.begin_job(self.owner, project["id"], project["revision"], "video", str(uuid4()))
                return True
            except StudioError:
                return False

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(submit, range(4))), 1)

    def test_unknown_submission_blocks_a_replacement_and_preserves_task_identity(self):
        self.prepare()
        project = self.store.get(self.owner, self.project["id"])
        job, _ = self.store.begin_job(self.owner, project["id"], project["revision"], "video", str(uuid4()))
        self.store.update_job(job["id"], state="unknown", task_id="known-provider-task")
        with self.assertRaises(StudioError):
            self.store.begin_job(self.owner, project["id"], project["revision"], "video", str(uuid4()))
        self.assertEqual(self.store.job(self.owner, job["id"])["task_id"], "known-provider-task")

    def test_empty_and_oversized_script_updates_are_bounded(self):
        project = self.store.update(self.owner, self.project["id"], 0, {"script": ""})
        self.assertEqual(project["script"], "")
        with self.assertRaises(StudioError):
            self.store.update(self.owner, project["id"], project["revision"], {"script": "x" * 3001})


if __name__ == "__main__":
    unittest.main()
