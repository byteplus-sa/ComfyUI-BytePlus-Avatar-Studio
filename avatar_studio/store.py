import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ACTIVE_STATES = {"preparing", "queued", "running", "unknown"}
IMAGE_FIELDS = {"character_prompt", "ratio", "reference_id"}
AUDIO_FIELDS = {"script", "voice_direction", "language"}
TEXT_LIMITS = {"title": 120, "script": 3000, "character_prompt": 2000, "voice_direction": 500, "motion_prompt": 2000}
RATIOS = {"1:1", "3:4", "9:16"}
LANGUAGES = {"English", "Chinese", "Japanese", "Korean", "Spanish", "Indonesian", "French", "German", "Filipino"}


class StudioError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def identifier(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise StudioError("Invalid identifier.") from None
    return value


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def uses_uploaded_asset(project, kind):
    return any(
        asset["id"] == project["current"][kind] and asset["kind"] == kind and asset.get("origin") == "upload"
        for asset in project["assets"]
    )


def validate_fields(fields):
    allowed = set(TEXT_LIMITS) | {"ratio", "language", "rights_confirmed", "enable_watermark"}
    if not isinstance(fields, dict) or set(fields) - allowed:
        raise StudioError("Unknown project fields.")
    for name, value in fields.items():
        if name in TEXT_LIMITS and (not isinstance(value, str) or len(value) > TEXT_LIMITS[name] or "\x00" in value):
            raise StudioError(f"{name.replace('_', ' ').capitalize()} exceeds its allowed length.")
        if name in {"rights_confirmed", "enable_watermark"} and type(value) is not bool:
            raise StudioError(f"{name} must be true or false.")
        if name == "ratio" and value not in RATIOS:
            raise StudioError("Unsupported portrait ratio.")
        if name == "language" and value not in LANGUAGES:
            raise StudioError("Unsupported narration language.")


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.media_dir = self.root / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "studio.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, data TEXT NOT NULL)"
        )
        self.db.commit()
        os.chmod(self.root / "studio.sqlite3", 0o600)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield

    def _project(self, owner, project_id):
        identifier(project_id)
        row = self.db.execute("SELECT data FROM projects WHERE id=? AND owner=?", (project_id, owner)).fetchone()
        if not row:
            raise StudioError("Project not found.", 404)
        return json.loads(row["data"])

    def _save(self, project):
        project["updated_at"] = time.time()
        self.db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(project), project["id"]))

    def _jobs(self, project_id):
        return [
            json.loads(row["data"])
            for row in self.db.execute("SELECT data FROM jobs WHERE project_id=?", (project_id,))
        ]

    def _idle(self, project_id):
        if any(job["state"] in ACTIVE_STATES for job in self._jobs(project_id)):
            raise StudioError("An operation is still active or needs recovery. Resolve it before changing inputs.", 409)

    def _revision(self, project, revision):
        if type(revision) is not int or project["revision"] != revision:
            raise StudioError("The project changed. Refresh before trying again.", 409)

    def create(self, owner, title="Untitled avatar"):
        validate_fields({"title": title})
        project: dict[str, Any] = {
            "id": str(uuid4()),
            "title": title.strip() or "Untitled avatar",
            "revision": 0,
            "script": "",
            "character_prompt": "",
            "voice_direction": "Warm, clear, natural delivery.",
            "language": "English",
            "ratio": "3:4",
            "motion_prompt": "",
            "rights_confirmed": True,
            "enable_watermark": True,
            "reference_id": None,
            "current": {"image": None, "audio": None, "video": None},
            "approvals": {"image": None, "audio": None},
            "assets": [],
            "updated_at": time.time(),
        }
        with self.transaction():
            self.db.execute("INSERT INTO projects VALUES (?,?,?)", (project["id"], owner, json.dumps(project)))
        return self.get(owner, project["id"])

    def get(self, owner, project_id):
        with self.transaction():
            project = self._project(owner, project_id)
            project["jobs"] = self._jobs(project_id)
            return project

    def list(self, owner):
        with self.transaction():
            projects = [
                json.loads(row["data"]) for row in self.db.execute("SELECT data FROM projects WHERE owner=?", (owner,))
            ]
        return sorted(
            [{"id": item["id"], "title": item["title"], "updated_at": item["updated_at"]} for item in projects],
            key=lambda item: item["updated_at"],
            reverse=True,
        )

    def update(self, owner, project_id, revision, fields):
        validate_fields(fields)
        with self.transaction():
            project = self._project(owner, project_id)
            self._revision(project, revision)
            self._idle(project_id)
            changed = {name for name, value in fields.items() if project[name] != value}
            project.update(fields)
            if changed & IMAGE_FIELDS and not uses_uploaded_asset(project, "image"):
                project["approvals"]["image"] = None
                project["current"]["image"] = None
            if changed & AUDIO_FIELDS and not uses_uploaded_asset(project, "audio"):
                project["approvals"]["audio"] = None
                project["current"]["audio"] = None
            if changed:
                project["current"]["video"] = None
                project["revision"] += 1
                self._save(project)
        return self.get(owner, project_id)

    def asset_path(self, asset):
        path = (self.media_dir / asset["filename"]).resolve()
        if not path.is_relative_to(self.media_dir) or not path.is_file():
            raise StudioError("Asset is missing or invalid.", 404)
        return path

    def add_asset(self, owner, project_id, kind, path, metadata):
        if kind not in {"image", "audio", "video", "reference"}:
            raise StudioError("Invalid asset kind.")
        path = Path(path).resolve()
        if not path.is_relative_to(self.media_dir) or not path.is_file():
            raise StudioError("Invalid asset location.")
        asset = {
            "id": str(uuid4()),
            "kind": kind,
            "filename": path.name,
            "sha256": digest(path),
            "bytes": path.stat().st_size,
            "origin": "upload" if kind == "reference" else "generated",
            **metadata,
        }
        with self.transaction():
            project = self._project(owner, project_id)
            project["assets"].append(asset)
            if kind == "reference":
                project["reference_id"] = asset["id"]
                if not uses_uploaded_asset(project, "image"):
                    project["current"]["image"] = None
                    project["approvals"]["image"] = None
            else:
                project["current"][kind] = asset["id"]
                if kind in {"image", "audio"}:
                    project["approvals"][kind] = None
            if kind != "video":
                project["current"]["video"] = None
            project["revision"] += 1
            self._save(project)
        return asset

    def remove_reference(self, owner, project_id, revision):
        with self.transaction():
            project = self._project(owner, project_id)
            self._revision(project, revision)
            self._idle(project_id)
            project["reference_id"] = None
            if not uses_uploaded_asset(project, "image"):
                project["current"]["image"] = None
                project["approvals"]["image"] = None
            project["current"]["video"] = None
            project["revision"] += 1
            self._save(project)
        return self.get(owner, project_id)

    def asset(self, owner, project_id, asset_id):
        identifier(asset_id)
        project = self.get(owner, project_id)
        for asset in project["assets"]:
            if asset["id"] == asset_id:
                return asset
        raise StudioError("Asset not found.", 404)

    def _approved(self, project, kind):
        approval = project["approvals"][kind]
        asset = next((item for item in project["assets"] if item["id"] == project["current"][kind]), None)
        if not asset or not approval or approval["asset_id"] != asset["id"] or approval["sha256"] != asset["sha256"]:
            raise StudioError(f"Approve the current {kind} before generating a video.", 409)
        if digest(self.asset_path(asset)) != asset["sha256"]:
            raise StudioError("Approved asset bytes changed. Regenerate and review again.", 409)
        return asset

    def approve(self, owner, project_id, revision, kind, asset_id, sha256):
        if kind not in {"image", "audio"}:
            raise StudioError("Only portraits and narration can be approved.")
        with self.transaction():
            project = self._project(owner, project_id)
            self._revision(project, revision)
            self._idle(project_id)
            asset = next((item for item in project["assets"] if item["id"] == asset_id and item["kind"] == kind), None)
            if not asset or project["current"][kind] != asset_id or asset["sha256"] != sha256:
                raise StudioError("This asset is no longer the current review candidate.", 409)
            if digest(self.asset_path(asset)) != sha256:
                raise StudioError("Asset bytes changed. Review a new candidate.", 409)
            if kind == "audio" and not 4 <= asset.get("duration", 0) <= 300:
                raise StudioError("OmniHuman requires audio between 4 and 300 seconds.")
            project["approvals"][kind] = {"asset_id": asset_id, "sha256": sha256, "approved_at": time.time()}
            project["revision"] += 1
            self._save(project)
        return self.get(owner, project_id)

    def begin_job(self, owner, project_id, revision, kind, operation_id):
        identifier(operation_id)
        if kind not in {"image", "audio", "video"}:
            raise StudioError("Invalid generation stage.")
        with self.transaction():
            project = self._project(owner, project_id)
            existing = self.db.execute("SELECT data FROM jobs WHERE id=?", (operation_id,)).fetchone()
            if existing:
                job = json.loads(existing["data"])
                if job["project_id"] != project_id or job["kind"] != kind:
                    raise StudioError("Operation identity already used.", 409)
                return job, False
            self._revision(project, revision)
            self._idle(project_id)
            assets = {}
            if kind == "video":
                assets = {stage: self._approved(project, stage) for stage in ("image", "audio")}
            job = {
                "id": operation_id,
                "project_id": project_id,
                "owner": owner,
                "kind": kind,
                "state": "preparing",
                "prompt_id": operation_id,
                "task_id": None,
                "message": "Preparing workflow.",
                "assets": assets,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self.db.execute("INSERT INTO jobs VALUES (?,?,?)", (job["id"], project_id, json.dumps(job)))
            project["revision"] += 1
            self._save(project)
        return job, True

    def job(self, owner, job_id):
        identifier(job_id)
        with self.transaction():
            row = self.db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise StudioError("Operation not found.", 404)
            job = json.loads(row["data"])
            self._project(owner, job["project_id"])
            return job

    def update_job(self, job_id, **fields):
        with self.transaction():
            row = self.db.execute("SELECT data FROM jobs WHERE id=?", (identifier(job_id),)).fetchone()
            if not row:
                raise StudioError("Operation not found.", 404)
            job = json.loads(row["data"])
            job.update(fields)
            job["updated_at"] = time.time()
            self.db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job), job_id))
        return job

    def pending_jobs(self):
        with self.transaction():
            return [
                json.loads(row["data"])
                for row in self.db.execute("SELECT data FROM jobs")
                if json.loads(row["data"])["state"] in ACTIVE_STATES
            ]
