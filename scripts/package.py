import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

PACKAGE_NAME = "ComfyUI-BytePlus-Avatar-Studio"
ROOT_FILES = (
    "__init__.py",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "INTER_FONT_LICENSE.txt",
    "CVA_LICENSE.txt",
    "avatar_studio/__init__.py",
    "web/extension.js",
    "studio_dist/index.html",
)
ASSET_SUFFIXES = {".js", ".css", ".woff2"}


def checked_file(root, path):
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Symlinks are not allowed in the distribution: {relative}")
    if not path.is_file():
        raise ValueError(f"Required distribution file is missing: {relative}")
    return path


def manifest(root):
    files = {checked_file(root, root / name) for name in ROOT_FILES}
    files.update(checked_file(root, path) for path in (root / "avatar_studio").glob("*.py"))
    files.update(
        checked_file(root, path) for path in (root / "studio_dist/assets").glob("*") if path.suffix in ASSET_SUFFIXES
    )
    index = (root / "studio_dist/index.html").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', index)
    suffixes = set()
    prefix = "/byteplus/avatar-studio/assets/"
    for reference in references:
        if not reference.startswith(prefix):
            raise ValueError("The built frontend must reference same-origin Studio assets.")
        filename = reference[len(prefix) :]
        if "/" in filename or "\\" in filename or Path(filename).suffix not in ASSET_SUFFIXES:
            raise ValueError("The built frontend contains an unsupported asset reference.")
        selected = checked_file(root, root / "studio_dist/assets" / filename)
        suffixes.add(selected.suffix)
        if selected not in files:
            raise ValueError(f"Referenced asset is not included: {filename}")
    if not {".js", ".css"} <= suffixes:
        raise ValueError("Build the frontend before packaging; JavaScript and CSS references are required.")
    return sorted(files)


def package(root):
    root = Path(root).resolve()
    metadata = checked_file(root, root / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", metadata)
    version = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$', project[1], re.MULTILINE) if project else None
    if not version or not re.search(rf'^name\s*=\s*"{PACKAGE_NAME}"\s*$', project[1], re.MULTILINE):
        raise ValueError("The project name/version metadata is invalid.")
    frontend = json.loads(checked_file(root, root / "frontend/package.json").read_text(encoding="utf-8"))
    if frontend.get("version") != version[1]:
        raise ValueError("Frontend and backend versions must match.")
    files = manifest(root)
    output = root / f"{PACKAGE_NAME}-{version[1]}.zip"
    descriptor, name = tempfile.mkstemp(prefix=".package-", suffix=".zip", dir=root)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for source in files:
                entry = zipfile.ZipInfo(f"{PACKAGE_NAME}/{source.relative_to(root).as_posix()}", (1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("Distribution integrity check failed.")
        checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, output)
        output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n", encoding="ascii")
    finally:
        temporary.unlink(missing_ok=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package only the built Studio runtime and required licenses.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    print(package(arguments.root))
