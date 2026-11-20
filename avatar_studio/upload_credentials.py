import hashlib
import json
import os
import stat
import tempfile
import threading
from pathlib import Path

from .store import StudioError

MAX_KEY_LENGTH = 4096
MAX_FILE_BYTES = 16 * 1024


def validate_upload_key(value):
    if not isinstance(value, str) or len(value) > MAX_KEY_LENGTH:
        raise StudioError("Enter a valid Comfy.org upload API key.")
    value = value.strip()
    if not value or any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise StudioError("Enter an upload API key without spaces or control characters.")
    return value


class UploadCredentials:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.lock = threading.RLock()

    def _path(self, owner):
        if not isinstance(owner, str) or not owner or len(owner) > 512:
            raise StudioError("A valid ComfyUI user is required.", 401)
        name = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        return self.root / f"{name}.json"

    def _check_directory(self, create=False):
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise StudioError("The credential directory is unavailable.", 503)
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name == "posix":
                self.root.chmod(0o700)

    def read(self, owner):
        path = self._path(owner)
        with self.lock:
            try:
                self._check_directory()
                if path.is_symlink():
                    raise StudioError("Invalid credential file.", 503)
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
                        raise StudioError("Invalid credential file.", 503)
                    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
                        raise StudioError("Credential permissions are not private.", 503)
                    text = stream.read(MAX_FILE_BYTES + 1)
                if len(text.encode("utf-8")) > MAX_FILE_BYTES:
                    raise StudioError("Invalid credential file.", 503)
                data = json.loads(text)
                if (
                    not isinstance(data, dict)
                    or set(data) != {"version", "upload_key"}
                    or type(data["version"]) is not int
                    or data["version"] != 1
                ):
                    raise StudioError("Invalid credential file.", 503)
                return validate_upload_key(data["upload_key"])
            except FileNotFoundError:
                return ""
            except (OSError, UnicodeError, ValueError, StudioError):
                raise StudioError(
                    "The saved upload key could not be read. Replace or remove it in Settings.", 503
                ) from None

    def status(self, owner):
        return {"configured": bool(self.read(owner))}

    def save(self, owner, value):
        path = self._path(owner)
        key = validate_upload_key(value)
        temporary = None
        with self.lock:
            try:
                self._check_directory(create=True)
                descriptor, name = tempfile.mkstemp(prefix=".upload-key-", dir=self.root)
                temporary = Path(name)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    if os.name == "posix":
                        os.fchmod(stream.fileno(), 0o600)
                    json.dump({"version": 1, "upload_key": key}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            except (OSError, StudioError):
                raise StudioError(
                    "The upload key could not be saved. The previous saved key was not replaced.", 503
                ) from None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def remove(self, owner):
        path = self._path(owner)
        with self.lock:
            try:
                self._check_directory()
                path.unlink(missing_ok=True)
            except (OSError, StudioError):
                raise StudioError("The saved upload key could not be removed.", 503) from None
