import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from avatar_studio.store import StudioError
from avatar_studio.upload_credentials import UploadCredentials, validate_upload_key


class UploadCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "credentials"
        self.credentials = UploadCredentials(self.root)

    def test_missing_key_has_no_disk_side_effects(self):
        self.assertEqual(self.credentials.status("default"), {"configured": False})
        self.assertEqual(self.credentials.read("default"), "")
        self.assertFalse(self.root.exists())

    def test_saved_key_survives_reopening_and_status_never_returns_it(self):
        self.credentials.save("default", "noncredential-persistence-fixture")
        reopened = UploadCredentials(self.root)
        self.assertEqual(reopened.read("default"), "noncredential-persistence-fixture")
        self.assertEqual(reopened.status("default"), {"configured": True})
        self.assertNotIn("fixture", json.dumps(reopened.status("default")))

    def test_replacement_and_removal_do_not_affect_another_owner(self):
        self.credentials.save("alice", "alice-fixture")
        self.credentials.save("bob", "bob-fixture")
        self.credentials.save("alice", "replacement-fixture")
        self.assertEqual(self.credentials.read("alice"), "replacement-fixture")
        self.credentials.remove("alice")
        self.credentials.remove("alice")
        self.assertEqual(self.credentials.read("alice"), "")
        self.assertEqual(self.credentials.read("bob"), "bob-fixture")

    def test_filenames_are_not_derived_from_owner_paths_and_permissions_are_private(self):
        self.credentials.save("../../outside", "noncredential-fixture")
        files = list(self.root.iterdir())
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^[a-f0-9]{64}\.json$")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)

    def test_invalid_keys_are_rejected_without_writing_files(self):
        for value in (None, 42, "", "  ", "line\nbreak", "invalid\0key", "invalid key", "invalidé", "x" * 4097):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(StudioError):
                self.credentials.save("default", value)
        self.assertFalse(self.root.exists())
        self.assertEqual(validate_upload_key("  valid-fixture  "), "valid-fixture")

    def test_corrupt_file_fails_closed_without_exposing_contents_and_can_be_replaced(self):
        self.credentials.save("default", "noncredential-fixture")
        path = next(self.root.glob("*.json"))
        path.write_text("private-malformed-fixture")
        with self.assertRaises(StudioError) as failure:
            self.credentials.read("default")
        self.assertNotIn("private-malformed-fixture", str(failure.exception))
        self.credentials.save("default", "new-fixture")
        self.assertEqual(self.credentials.read("default"), "new-fixture")

    def test_failed_atomic_replace_preserves_existing_key_and_cleans_temporary_file(self):
        self.credentials.save("default", "original-fixture")
        with (
            patch("avatar_studio.upload_credentials.os.replace", side_effect=OSError("private-fixture")),
            self.assertRaises(StudioError) as failure,
        ):
            self.credentials.save("default", "replacement-fixture")
        self.assertNotIn("private-fixture", str(failure.exception))
        self.assertEqual(self.credentials.read("default"), "original-fixture")
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_symlinked_file_is_not_read_and_remove_does_not_touch_its_target(self):
        self.credentials.save("default", "original-fixture")
        path = next(self.root.glob("*.json"))
        target = Path(self.temporary.name) / "outside.json"
        target.write_text('{"version":1,"upload_key":"outside-fixture"}')
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(StudioError):
            self.credentials.read("default")
        self.credentials.remove("default")
        self.assertTrue(target.exists())

    def test_concurrent_owner_updates_remain_isolated(self):
        owners = [f"owner-{index}" for index in range(8)]
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda owner: self.credentials.save(owner, f"{owner}-fixture"), owners))
        for owner in owners:
            self.assertEqual(self.credentials.read(owner), f"{owner}-fixture")

    def test_invalid_owner_is_rejected(self):
        for owner in (None, "", 12, "x" * 513):
            with self.assertRaises(StudioError):
                self.credentials.status(owner)

    def test_maximum_length_key_round_trips_and_oversized_file_is_rejected(self):
        value = "\\" * 4096
        self.credentials.save("default", value)
        self.assertEqual(self.credentials.read("default"), value)
        next(self.root.glob("*.json")).write_bytes(b"x" * (16 * 1024 + 1))
        with self.assertRaises(StudioError):
            self.credentials.read("default")

    def test_symlinked_directory_is_never_used(self):
        target = Path(self.temporary.name) / "other"
        target.mkdir()
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises(StudioError):
            self.credentials.save("default", "fixture")
        with self.assertRaises(StudioError):
            self.credentials.read("default")
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "POSIX file permission contract")
    def test_a_saved_file_with_broad_permissions_fails_closed(self):
        self.credentials.save("default", "fixture")
        next(self.root.glob("*.json")).chmod(0o644)
        with self.assertRaises(StudioError):
            self.credentials.read("default")


if __name__ == "__main__":
    unittest.main()
