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

    def test_portrait_and_narration_can_run_independently(self):
        image, _ = self.store.begin_job(self.owner, self.project["id"], 0, "image", str(uuid4()))
        current = self.store.get(self.owner, self.project["id"])
        audio, _ = self.store.begin_job(self.owner, current["id"], current["revision"], "audio", str(uuid4()))
        self.assertEqual({job["kind"] for job in self.store.pending_jobs()}, {"image", "audio"})
        for kind in ("image", "audio", "video"):
            current = self.store.get(self.owner, self.project["id"])
            with self.subTest(kind=kind), self.assertRaises(StudioError):
                self.store.begin_job(self.owner, current["id"], current["revision"], kind, str(uuid4()))
        self.store.update_job(image["id"], state="done")
        current = self.store.get(self.owner, self.project["id"])
        self.store.begin_job(self.owner, current["id"], current["revision"], "image", str(uuid4()))
        self.assertEqual(self.store.job(self.owner, audio["id"])["state"], "preparing")

    def test_other_stage_inputs_and_approvals_remain_available_during_preparation(self):
        portrait = self.asset("image")
        current = self.store.get(self.owner, self.project["id"])
        self.store.begin_job(self.owner, current["id"], current["revision"], "audio", str(uuid4()))
        current = self.store.get(self.owner, current["id"])
        current = self.store.approve(
            self.owner, current["id"], current["revision"], "image", portrait["id"], portrait["sha256"]
        )
        self.assertIsNotNone(current["approvals"]["image"])
        current = self.store.update(
            self.owner, current["id"], current["revision"], {"character_prompt": "New portrait"}
        )
        for fields in ({"script": "Changed narration"}, {"voice_direction": "Different voice"}):
            with self.subTest(fields=fields), self.assertRaises(StudioError):
                self.store.update(self.owner, current["id"], current["revision"], fields)

    def test_stage_token_accepts_unrelated_completion_but_rejects_changed_source(self):
        original = self.store.get(self.owner, self.project["id"])
        self.asset("image")
        _, created = self.store.begin_job(
            self.owner,
            original["id"],
            original["revision"],
            "audio",
            str(uuid4()),
            generation_token=original["generation_tokens"]["audio"],
        )
        self.assertTrue(created)
        with self.assertRaises(StudioError):
            self.store.begin_job(
                self.owner,
                original["id"],
                original["revision"],
                "image",
                str(uuid4()),
                generation_token=original["generation_tokens"]["image"],
            )

    def test_unknown_preparation_blocks_only_its_stage_and_video(self):
        image, _ = self.store.begin_job(self.owner, self.project["id"], 0, "image", str(uuid4()))
        self.store.update_job(image["id"], state="unknown")
        current = self.store.get(self.owner, self.project["id"])
        self.store.begin_job(self.owner, current["id"], current["revision"], "audio", str(uuid4()))
        current = self.store.get(self.owner, current["id"])
        with self.assertRaises(StudioError):
            self.store.begin_job(self.owner, current["id"], current["revision"], "image", str(uuid4()))

    def test_concurrent_preparation_clicks_accept_at_most_one_job_per_stage(self):
        project = self.store.get(self.owner, self.project["id"])

        def submit(kind):
            try:
                self.store.begin_job(
                    self.owner,
                    project["id"],
                    project["revision"],
                    kind,
                    str(uuid4()),
                    generation_token=project["generation_tokens"][kind],
                )
                return kind
            except StudioError:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            accepted = list(pool.map(submit, ["image", "audio", "image", "audio"]))
        self.assertEqual(sorted(kind for kind in accepted if kind), ["audio", "image"])


if __name__ == "__main__":
    unittest.main()
