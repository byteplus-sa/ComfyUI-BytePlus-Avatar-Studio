import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.check_registry_package import check_registry_package
from scripts.package import manifest, package


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        for directory in ("avatar_studio", "web", "studio_dist/assets", "frontend", "credentials", "docs"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in (
            "__init__.py",
            "README.md",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "INTER_FONT_LICENSE.txt",
            "CVA_LICENSE.txt",
        ):
            (self.root / name).write_text("distribution fixture")
        (self.root / "avatar_studio/__init__.py").write_text("")
        (self.root / "avatar_studio/routes.py").write_text("PREFIX = '/byteplus/avatar-studio'")
        (self.root / "web/extension.js").write_text("export const launcher = true")
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "ComfyUI-BytePlus-Avatar-Studio"\nversion = "0.1.0"\n'
        )
        (self.root / "frontend/package.json").write_text(json.dumps({"version": "0.1.0"}))
        (self.root / "studio_dist/index.html").write_text(
            '<script src="/byteplus/avatar-studio/assets/app.js"></script>'
            '<link rel="stylesheet" href="/byteplus/avatar-studio/assets/app.css">'
        )
        (self.root / "studio_dist/assets/app.js").write_text("export const compiled = true")
        (self.root / "studio_dist/assets/app.css").write_text("body {color:white}")

    def test_only_runtime_files_and_licenses_are_shipped(self):
        for name in (
            ".env",
            "credentials/owner.json",
            "studio.sqlite3",
            "PLAN_DRAFT.md",
            "frontend/secret.txt",
            "docs/development.md",
            "studio_dist/assets/debug.map",
        ):
            (self.root / name).write_text("private-fixture")
        archive = package(self.root)
        with zipfile.ZipFile(archive) as distribution:
            self.assertIsNone(distribution.testzip())
            names = distribution.namelist()
            self.assertIn("ComfyUI-BytePlus-Avatar-Studio/studio_dist/assets/app.js", names)
            self.assertIn("ComfyUI-BytePlus-Avatar-Studio/CVA_LICENSE.txt", names)
            self.assertFalse(any("private-fixture" in distribution.read(name).decode() for name in names))
        self.assertTrue(archive.with_suffix(".zip.sha256").is_file())

    def test_reference_docs_are_excluded_from_registry_packaging(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("docs/", (root / ".comfyignore").read_text().splitlines())
        self.assertFalse(any("docs" in path.relative_to(root).parts for path in manifest(root)))

    def test_two_builds_have_identical_contents(self):
        first = package(self.root).read_bytes()
        self.assertEqual(package(self.root).read_bytes(), first)

    def test_missing_referenced_asset_fails_before_replacing_a_package(self):
        archive = package(self.root)
        original = archive.read_bytes()
        (self.root / "studio_dist/assets/app.js").unlink()
        with self.assertRaises(ValueError):
            package(self.root)
        self.assertEqual(archive.read_bytes(), original)

    def test_symlinked_runtime_file_is_rejected(self):
        target = Path(self.temporary.name) / "outside.py"
        target.write_text("outside fixture")
        (self.root / "avatar_studio/routes.py").unlink()
        (self.root / "avatar_studio/routes.py").symlink_to(target)
        with self.assertRaises(ValueError):
            package(self.root)

    def test_frontend_backend_version_mismatch_is_rejected(self):
        (self.root / "frontend/package.json").write_text('{"version":"0.2.0"}')
        with self.assertRaises(ValueError):
            package(self.root)

    def test_failed_write_preserves_previous_package_and_removes_temporary_file(self):
        archive = package(self.root)
        original = archive.read_bytes()
        with (
            patch("scripts.package.zipfile.ZipFile.writestr", side_effect=OSError("write failure")),
            self.assertRaises(OSError),
        ):
            package(self.root)
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".package-*")), [])

    def registry_archive(self, *, omit=None, replace=None, extra=None):
        icon = self.root / "assets/registry-icon.jpg"
        icon.parent.mkdir(exist_ok=True)
        icon.write_bytes(b"synthetic-icon")
        archive = self.root / "node.zip"
        with zipfile.ZipFile(archive, "w") as distribution:
            for path in [*manifest(self.root), icon]:
                name = path.relative_to(self.root).as_posix()
                if name != omit:
                    distribution.writestr(name, b"changed-runtime" if name == replace else path.read_bytes())
            if extra:
                distribution.writestr(extra, b"private-fixture")
        return archive

    def test_registry_archive_contains_the_exact_tested_runtime_and_icon(self):
        archive = self.registry_archive()
        self.assertEqual(check_registry_package(self.root, archive), len(manifest(self.root)) + 1)

    def test_registry_archive_rejects_secrets_development_files_and_traversal(self):
        for extra in (
            ".env",
            "tests/test_example.py",
            "docs/development.md",
            "../outside.py",
            "/absolute.py",
            "unexpected.txt",
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                check_registry_package(self.root, self.registry_archive(extra=extra))

    def test_registry_archive_rejects_missing_or_changed_runtime_files(self):
        for changes in ({"omit": "studio_dist/assets/app.js"}, {"replace": "web/extension.js"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                check_registry_package(self.root, self.registry_archive(**changes))


if __name__ == "__main__":
    unittest.main()
