import argparse
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def run(core, companion, studio, port):
    for path in (
        core / "main.py",
        companion / "__init__.py",
        studio / "__init__.py",
        studio / "studio_dist/index.html",
    ):
        if not path.is_file():
            raise ValueError(f"Required smoke-test file is missing: {path}")
    environment = {
        name: value
        for name, value in os.environ.items()
        if not any(marker in name.upper() for marker in ("TOKEN", "SECRET", "API_KEY", "ACCESS_KEY", "ACCESSKEY"))
        and not name.startswith(("BYTEPLUS_", "ARK_", "VOLC_", "VOLCENGINE_"))
    }
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(core), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    help_text = subprocess.run(
        [sys.executable, str(core / "main.py"), "--help"],
        cwd=core,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="avatar-native-server-") as directory:
        root = Path(directory)
        for name in ("custom_nodes", "user", "input", "output", "temp"):
            (root / name).mkdir()
        companion_name = "ComfyUI-BytePlus-ModelArk"
        studio_name = "ComfyUI-BytePlus-Avatar-Studio"
        (root / "custom_nodes" / companion_name).symlink_to(companion, target_is_directory=True)
        (root / "custom_nodes" / studio_name).symlink_to(studio, target_is_directory=True)
        command = [
            sys.executable,
            str(core / "main.py"),
            "--cpu",
            *(["--offline"] if "--offline" in help_text else []),
            "--disable-auto-launch",
            "--listen",
            "127.0.0.1",
            "--port",
            str(port),
            "--base-directory",
            str(root),
            "--user-directory",
            str(root / "user"),
            "--temp-directory",
            str(root / "temp"),
            "--database-url",
            f"sqlite:///{root / 'user/comfyui.db'}",
            "--disable-all-custom-nodes",
            "--whitelist-custom-nodes",
            companion_name,
            studio_name,
        ]
        process = subprocess.Popen(command, cwd=core, env=environment)
        try:
            return process.wait()
        except KeyboardInterrupt:
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an isolated, credential-free native ComfyUI smoke server.")
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--companion-root", type=Path, required=True)
    parser.add_argument("--studio-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--port", type=int, default=8209)
    arguments = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)
    raise SystemExit(
        run(
            arguments.comfy_root.resolve(),
            arguments.companion_root.resolve(),
            arguments.studio_root.resolve(),
            arguments.port,
        )
    )
