import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.package import manifest


def check_registry_package(root, archive):
    root = Path(root).resolve()
    expected = {path.relative_to(root).as_posix(): path for path in manifest(root)}
    expected["assets/registry-icon.jpg"] = root / "assets/registry-icon.jpg"
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("Registry archive must contain exactly the approved runtime files and icon.")
        if package.testzip() is not None:
            raise ValueError("Registry archive integrity check failed.")
        for name, path in expected.items():
            if package.read(name) != path.read_bytes():
                raise ValueError(f"Registry archive differs from the tested source: {name}")
    return len(expected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify the exact runtime-only Comfy Registry archive.")
    parser.add_argument("archive", type=Path)
    arguments = parser.parse_args()
    count = check_registry_package(Path(__file__).resolve().parents[1], arguments.archive)
    print(f"Registry package verified: {count} runtime files.")
