import asyncio
import inspect
import logging
from contextlib import suppress
from functools import partial
from uuid import uuid4

from . import media
from .login_sessions import LoginSessions
from .store import ACTIVE_STATES, StudioError
from .upload_credentials import UploadCredentials
from .workflows import build_workflow

logger = logging.getLogger("BytePlusAvatarStudio")


class StudioService:
    def __init__(self, store, bridge):
        self.store = store
        self.bridge = bridge
        self.login_sessions = LoginSessions(bridge)
        self.upload_credentials = UploadCredentials(store.root / "credentials")
        self.locks = {}
        self.monitor = None

    def start(self):
        if self.monitor is None or self.monitor.done():
            self.monitor = asyncio.create_task(self.watch())

    async def close(self):
        self.login_sessions.close()
        if self.monitor:
            self.monitor.cancel()
            with suppress(asyncio.CancelledError):
                await self.monitor
        if close := getattr(self.bridge, "close", None):
            result = close()
            if inspect.isawaitable(result):
                await result
        self.store.close()

    async def generate(self, owner, project_id, revision, kind, operation_id, sensitive, generation_token=None):
        lock = self.locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            job, created = self.store.begin_job(
                owner, project_id, revision, kind, operation_id, generation_token=generation_token
            )
            if not created:
                return self.store.get(owner, project_id)
            try:
                self.bridge.stage_ready(kind, sensitive)
                project = self.store.get(owner, project_id)
                sources = {}
                if kind == "image" and project["reference_id"]:
                    reference = self.store.asset(owner, project_id, project["reference_id"])
                    sources["reference"] = await asyncio.to_thread(self.bridge.source, reference, self.store)
                if kind == "video":
                    for stage in ("image", "audio"):
                        sources[stage] = await asyncio.to_thread(self.bridge.source, job["assets"][stage], self.store)
                graph = build_workflow(project, job, sources)
            except StudioError as error:
                self.store.update_job(job["id"], state="failed", message=str(error))
                raise
            except Exception:
                self.store.update_job(job["id"], state="failed", message="Could not prepare the local workflow.")
                raise StudioError("Could not prepare the local workflow.", 500) from None
            self.store.update_job(
                job["id"],
                state="unknown",
                runner="preparation" if kind in {"image", "audio"} else "queue",
                message="Submitting once; acceptance is not yet confirmed.",
            )
            try:
                await self.bridge.submit(graph, job["prompt_id"], sensitive, owner)
            except StudioError as error:
                self.store.update_job(job["id"], state="failed", message=str(error))
                raise
            except Exception:
                self.store.update_job(
                    job["id"], state="unknown", message="Submission acceptance is unknown. Do not regenerate."
                )
                raise StudioError("Submission acceptance is unknown. Keep this operation for recovery.", 503) from None
            self.store.update_job(
                job["id"],
                state="running" if kind in {"image", "audio"} else "queued",
                message="Generating candidate." if kind in {"image", "audio"} else "Waiting in the ComfyUI queue.",
            )
            self.start()
            return self.store.get(owner, project_id)

    async def recover(self, owner, job_id, task_id):
        if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
            raise StudioError("Enter the original OmniHuman task ID.")
        if not all(character.isascii() and (character.isalnum() or character in "_-") for character in task_id):
            raise StudioError("Invalid OmniHuman task ID.")
        job = self.store.job(owner, job_id)
        lock = self.locks.setdefault(job["project_id"], asyncio.Lock())
        async with lock:
            job = self.store.job(owner, job_id)
            if job["kind"] != "video" or job["state"] not in {"unknown", "failed"}:
                raise StudioError("Only unresolved video operations can be recovered.", 409)
            if job.get("task_id") and task_id != job["task_id"]:
                raise StudioError("The recovery task ID must match the original operation.", 409)
            project = self.store.get(owner, job["project_id"])
            if any(other["id"] != job_id and other["state"] in ACTIVE_STATES for other in project["jobs"]):
                raise StudioError("Another operation is active.", 409)
            self.bridge.stage_ready("video", {}, require_upload=False)
            job = self.store.update_job(
                job_id,
                task_id=task_id,
                recovering=True,
                prompt_id=str(uuid4()),
                state="unknown",
                message="Collecting the existing task; no new generation.",
            )
            graph = build_workflow(project, job, {})
            try:
                await self.bridge.submit(graph, job["prompt_id"], {}, owner)
            except StudioError:
                raise
            except Exception:
                raise StudioError("Could not queue task collection. No new generation was submitted.", 503) from None
            self.store.update_job(job_id, state="queued", message="Waiting to collect the original OmniHuman task.")
            self.start()
            return self.store.get(owner, job["project_id"])

    async def resolve(self, owner, job_id):
        job = self.store.job(owner, job_id)
        lock = self.locks.setdefault(job["project_id"], asyncio.Lock())
        async with lock:
            job = self.store.job(owner, job_id)
            if (
                job["kind"] not in {"image", "audio"}
                or job.get("runner") != "preparation"
                or job["state"] not in {"unknown", "dismissed"}
            ):
                raise StudioError("Only unresolved portrait or narration preparation can be dismissed.", 409)
            if job["state"] == "dismissed":
                return self.store.get(owner, job["project_id"])
            state = self.bridge.inspect(job)
            if state.get("state") not in {"unknown", "missing"}:
                raise StudioError(
                    "Preparation is still active or has a result to collect. Wait for collection before resolving.",
                    409,
                )
            self.store.resolve_job(owner, job_id)
            if release := getattr(self.bridge, "release", None):
                release(job["prompt_id"])
            return self.store.get(owner, job["project_id"])

    async def cancel(self, owner, job_id):
        job = self.store.job(owner, job_id)
        lock = self.locks.setdefault(job["project_id"], asyncio.Lock())
        async with lock:
            job = self.store.job(owner, job_id)
            if job["kind"] != "video" or not job.get("task_id") or job["state"] not in ACTIVE_STATES:
                raise StudioError("A known active OmniHuman task is required for cancellation.", 409)
            canceled = await self.bridge.cancel_task(job["task_id"])
            if canceled:
                self.store.update_job(
                    job_id, state="canceled", message="The provider confirmed queued-task cancellation."
                )
            else:
                self.store.update_job(
                    job_id, message="The provider did not cancel this task. Running work may continue and be billed."
                )
            return self.store.get(owner, job["project_id"])

    async def reference(self, owner, project_id, revision, data):
        return await self._import_media(owner, project_id, revision, "reference", data, media.prepare_reference)

    async def upload_candidate(self, owner, project_id, revision, kind, data):
        if kind not in {"image", "audio"}:
            raise StudioError("Only portraits and narration can be uploaded.")
        return await self._import_media(owner, project_id, revision, kind, data, partial(media.prepare_candidate, kind))

    async def _import_media(self, owner, project_id, revision, kind, data, prepare):
        with self.store.transaction():
            project = self.store._project(owner, project_id)
            self.store._revision(project, revision)
            self.store._idle(project_id, {"image" if kind == "reference" else kind})
        preparation = asyncio.create_task(asyncio.to_thread(prepare, data, self.store.media_dir))
        try:
            path, metadata = await asyncio.shield(preparation)
        except asyncio.CancelledError:
            try:
                path, _ = await preparation
            except Exception:
                logger.warning("Canceled media upload ended during preparation.")
            else:
                path.unlink(missing_ok=True)
            raise
        try:
            with self.store.transaction():
                project = self.store._project(owner, project_id)
                self.store._revision(project, revision)
                self.store._idle(project_id, {"image" if kind == "reference" else kind})
                self.store.add_asset(owner, project_id, kind, path, metadata)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.store.get(owner, project_id)

    async def tick(self, job):
        state = self.bridge.inspect(job)
        task_id = state.get("task_id") or job.get("task_id")
        if task_id and task_id != job.get("task_id"):
            self.store.update_job(job["id"], task_id=task_id)
        if state["state"] in {"queued", "running"}:
            self.store.update_job(
                job["id"],
                state=state["state"],
                task_id=task_id,
                message="Generating through ComfyUI."
                if state["state"] == "running"
                else "Waiting in the ComfyUI queue.",
            )
            return
        if state["state"] == "unknown" or (state["state"] == "missing" and job.get("runner") == "preparation"):
            self.store.update_job(
                job["id"],
                state="unknown",
                message="Preparation stopped without a confirmed result. Check provider usage before replacing it. "
                "The other preparation stage is still available.",
            )
            return
        if state["state"] in {"failed", "missing"}:
            unresolved = job["kind"] == "video" or state["state"] == "missing"
            message = (
                "Execution stopped. Keep the operation and original task ID; recover without regenerating."
                if unresolved
                else "Generation failed in ComfyUI. Check its queue errors before retrying."
            )
            self.store.update_job(
                job["id"], state="unknown" if unresolved else "failed", task_id=task_id, message=message
            )
            return
        outputs = state.get("outputs", {})
        candidates = (
            outputs.get("images", []) + outputs.get("audio", []) + outputs.get("videos", []) + outputs.get("gifs", [])
        )
        if not candidates:
            self.store.update_job(
                job["id"],
                state="unknown" if job["kind"] == "video" else "failed",
                task_id=task_id,
                message="No saved result was returned. Keep any task ID for recovery.",
            )
            return
        source = self.bridge.output_path(job, candidates[0])
        prepare = {"image": media.prepare_image, "audio": media.prepare_audio, "video": media.collect_video}[
            job["kind"]
        ]
        path, metadata = await asyncio.to_thread(prepare, source, self.store.media_dir)
        try:
            self.store.add_asset(job["owner"], job["project_id"], job["kind"], path, metadata)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.store.update_job(
            job["id"],
            state="done",
            task_id=task_id,
            message="Ready for review." if job["kind"] != "video" else "Video saved. Review before publishing.",
        )
        if release := getattr(self.bridge, "release", None):
            release(job["prompt_id"])

    async def watch(self):
        while True:
            for job in self.store.pending_jobs():
                try:
                    lock = self.locks.setdefault(job["project_id"], asyncio.Lock())
                    async with lock:
                        current = self.store.job(job["owner"], job["id"])
                        if current["state"] in ACTIVE_STATES:
                            await self.tick(current)
                except StudioError as error:
                    self.store.update_job(
                        job["id"], state="unknown" if job["kind"] == "video" else "failed", message=str(error)
                    )
                except Exception:
                    logger.warning(
                        "Avatar Studio could not inspect a local operation; no generation will be resubmitted."
                    )
                    self.store.update_job(
                        job["id"], state="unknown", message="Local collection failed. Keep this operation for recovery."
                    )
            await asyncio.sleep(1)
