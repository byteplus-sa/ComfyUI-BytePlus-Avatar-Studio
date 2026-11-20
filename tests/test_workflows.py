import unittest

from avatar_studio.store import StudioError
from avatar_studio.workflows import audio_prompt, build_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "character_prompt": "A fictional presenter",
            "ratio": "3:4",
            "script": "Hello, welcome.",
            "voice_direction": "Warm and clear.",
            "language": "English",
            "motion_prompt": "Gentle natural gestures.",
            "enable_watermark": True,
        }
        self.job = {"id": "example-job", "kind": "image"}

    def test_portrait_uses_seedream_55_and_native_reference_socket(self):
        graph = build_workflow(self.project, self.job, {"reference": "reference.png"})
        inputs = graph["avatar_example-job"]["inputs"]
        self.assertEqual(inputs["model"], "seedream 5.5")
        self.assertEqual(inputs["model.images.image_1"], ["reference", 0])
        self.assertEqual(inputs["model.generation_count"], 1)
        self.assertEqual(inputs["model.background"], "opaque")

    def test_no_reference_means_no_empty_image_socket(self):
        graph = build_workflow(self.project, self.job, {})
        self.assertNotIn("model.images.image_1", graph["avatar_example-job"]["inputs"])

    def test_audio_contains_unmodified_script_and_no_voice_reference(self):
        self.job["kind"] = "audio"
        graph = build_workflow(self.project, self.job, {})
        inputs = graph["avatar_example-job"]["inputs"]
        self.assertIn(self.project["script"], inputs["text_prompt"])
        self.assertEqual(inputs["reference_mode"], "text only")
        self.assertEqual(inputs["sample_rate"], "24000")
        self.assertEqual(inputs["speech_rate"], 0)
        self.assertEqual(inputs["pitch_rate"], 0)
        self.assertEqual(inputs["loudness_rate"], 0)

    def test_combined_audio_prompt_limit_includes_voice_direction(self):
        self.project["script"] = "x" * 3000
        with self.assertRaises(StudioError):
            audio_prompt(self.project)

    def test_empty_script_or_character_prompt_is_rejected_before_submission(self):
        for kind, field in (("image", "character_prompt"), ("audio", "script")):
            self.job["kind"] = kind
            self.project[field] = ""
            with self.subTest(kind=kind), self.assertRaises(StudioError):
                build_workflow(self.project, self.job, {})

    def test_video_connects_only_approved_sources_and_records_task_identity(self):
        self.job["kind"] = "video"
        graph = build_workflow(self.project, self.job, {"image": "approved.png", "audio": "approved.wav"})
        inputs = graph["avatar_example-job"]["inputs"]
        self.assertEqual(inputs["image"], ["portrait", 0])
        self.assertEqual(inputs["audio"], ["narration", 0])
        self.assertIsInstance(inputs["seed"], int)
        self.assertEqual(graph["record"]["inputs"]["task_id"], ["avatar_example-job", 1])
        self.assertEqual(graph["save"]["class_type"], "SaveVideo")

    def test_recovery_cannot_submit_new_generation_or_upload_sources(self):
        self.job.update(kind="video", task_id="provider-task", recovering=True)
        graph = build_workflow(self.project, self.job, {})
        self.assertEqual(graph["avatar_example-job"]["class_type"], "BytePlusOmniHumanTaskResult")
        self.assertNotIn("portrait", graph)
        self.assertNotIn("narration", graph)

    def test_regeneration_changes_local_seed_but_repeating_the_same_operation_preserves_it(self):
        for kind, field in (("image", "model.seed"), ("audio", "seed"), ("video", "seed")):
            sources = {"image": "approved.png", "audio": "approved.wav"}
            self.job.update(kind=kind, id="operation-one")
            first = build_workflow(self.project, self.job, sources)["avatar_operation-one"]["inputs"][field]
            repeated = build_workflow(self.project, self.job, sources)["avatar_operation-one"]["inputs"][field]
            self.job["id"] = "operation-two"
            replacement = build_workflow(self.project, self.job, sources)["avatar_operation-two"]["inputs"][field]
            with self.subTest(kind=kind):
                self.assertEqual(first, repeated)
                self.assertNotEqual(first, replacement)
                self.assertGreaterEqual(first, 0)
                self.assertLessEqual(first, 2**31 - 1)


if __name__ == "__main__":
    unittest.main()
