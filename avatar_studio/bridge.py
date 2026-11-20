import importlib
import inspect
import re
import shutil
import time
from pathlib import Path

from .store import StudioError, digest

REQUIRED_NODES = {
    "BytePlusSeedream",
    "BytePlusSeedAudio",
    "BytePlusOmniHuman",
    "BytePlusOmniHumanTaskResult",
    "BytePlusOmniHumanCancelTask",
    "BytePlusAvatarStudioTaskRecord",
    "LoadImage",
    "LoadAudio",
    "SaveImage",
    "SaveAudio",
    "SaveVideo",
}
KEYS = {"image": "BYTEPLUS_API_KEY", "audio": "BYTEPLUS_SEED_SPEECH_API_KEY", "video": "BYTEPLUS_CV_API_KEY"}


class ComfyBridge:
    def __init__(self, server):
        self.server = server
        self.nodes = importlib.import_module("nodes")
        self.paths = importlib.import_module("folder_paths")
        self.execution = importlib.import_module("execution")

    def companion_module(self, name):
        node = self.nodes.NODE_CLASS_MAPPINGS.get("BytePlusOmniHuman")
        if not node:
            raise StudioError("Install ComfyUI-BytePlus-ModelArk v0.10.0 or newer and restart ComfyUI.", 503)
        package = node.__module__.rsplit(".", 1)[0]
        return importlib.import_module(f"{package}.{name}")

    def setup(self):
        missing = sorted(REQUIRED_NODES - self.nodes.NODE_CLASS_MAPPINGS.keys())
        keys = {stage: False for stage in KEYS}
        version = None
        if "BytePlusOmniHuman" in self.nodes.NODE_CLASS_MAPPINGS:
            credentials = self.companion_module("credentials")
            keys = {stage: bool(credentials.get_setting(name)) for stage, name in KEYS.items()}
            node = self.nodes.NODE_CLASS_MAPPINGS["BytePlusOmniHuman"]
            module = importlib.import_module(node.__module__)
            if not module.__file__:
                raise StudioError("The companion package metadata is unavailable.", 503)
            metadata = Path(module.__file__).parent.parent / "pyproject.toml"
            if metadata.is_file():
                matched = re.search(r'^version\s*=\s*"([^"]+)"', metadata.read_text(), re.MULTILINE)
                version = matched.group(1) if matched else None
        version_ok = bool(
            version and re.fullmatch(r"\d+\.\d+\.\d+", version) and tuple(map(int, version.split("."))) >= (0, 10, 0)
        )
        return {"ready": not missing and version_ok, "missing_nodes": missing, "version": version, "credentials": keys}

    def stage_ready(self, kind, sensitive, require_upload=True):
        setup = self.setup()
        if not setup["ready"]:
            raise StudioError("Required companion/core nodes are missing or the companion is older than v0.10.0.", 503)
        if not setup["credentials"][kind]:
            raise StudioError(f"Set the {KEYS[kind]} credential in ComfyUI Settings > BytePlus.", 503)
        if (
            kind == "video"
            and require_upload
            and not (sensitive.get("api_key_comfy_org") or sensitive.get("auth_token_comfy_org"))
        ):
            raise StudioError("Connect your ComfyUI login or set an upload API key for portrait and narration media.")

    def login_client_connected(self, client_id):
        socket = self.server.sockets.get(client_id)
        return socket is not None and not socket.closed

    def send_login_request(self, client_id, data):
        if not self.login_client_connected(client_id):
            raise StudioError("The source ComfyUI tab is no longer connected.", 401)
        self.server.send_sync("byteplus_avatar_login", data, client_id)

    def source(self, asset, store):
        original = store.asset_path(asset)
        if digest(original) != asset["sha256"]:
            raise StudioError("Selected asset bytes changed. Review a new candidate.", 409)
        destination = Path(self.paths.get_input_directory()) / f"byteplus_avatar_{asset['id']}{original.suffix}"
        if not destination.exists() or digest(destination) != asset["sha256"]:
            shutil.copyfile(original, destination)
        return destination.name

    async def submit(self, graph, prompt_id, sensitive, owner):
        parameters = len(inspect.signature(self.execution.validate_prompt).parameters)
        if parameters >= 3:
            valid = await self.execution.validate_prompt(prompt_id, graph, None)
        elif parameters == 2:
            valid = await self.execution.validate_prompt(prompt_id, graph)
        else:
            result = self.execution.validate_prompt(graph)
            valid = await result if inspect.isawaitable(result) else result
        if not valid[0] or valid[3] or "save" not in valid[2]:
            raise StudioError(
                "The workflow does not match this ComfyUI installation. Update ComfyUI and the companion.", 422
            )
        extra = {
            "create_time": time.time_ns() // 1_000_000,
            "comfy_usage_source": "byteplus-avatar-studio",
            "user_id": owner,
        }
        queue = self.server.prompt_queue
        with queue.mutex:
            if sensitive.get("auth_token_comfy_org") and any(queue.get_current_queue()):
                raise StudioError(
                    "ComfyUI is busy. Wait for its queue to finish, then generate again with fresh ComfyUI login "
                    "authorization, or explicitly select an upload API key in Settings.",
                    409,
                )
            number = self.server.number
            self.server.number += 1
            queue.put((number, prompt_id, graph, extra, valid[2], sensitive))

    async def cancel_task(self, task_id):
        api = self.companion_module("omnihuman_api")
        try:
            canceled, _ = await api.cancel_task(api.get_omnihuman_client(), task_id)
            return canceled
        except Exception as error:
            provider_error = getattr(api, "RetryableRequestError", None)
            if (
                isinstance(provider_error, type)
                and isinstance(error, provider_error)
                and getattr(error, "status", None) == 400
                and str(error).startswith(api.get_text("err_omnihuman_api", status=400, code=50217, message=""))
            ):
                return False
            raise StudioError("Cancellation could not be confirmed. Remote work may still continue.", 503) from None

    def inspect(self, job):
        history = self.server.prompt_queue.get_history(job["prompt_id"]).get(job["prompt_id"])
        task_id = job.get("task_id")
        if job["kind"] == "video":
            module = self.companion_module("nodes_omnihuman")
            reader = getattr(module, "_read_handle", None)
            if reader:
                handle = reader(f"avatar_{job['id']}")
                if handle:
                    task_id = handle.get("task_id") or task_id
        if history:
            outputs = history.get("outputs", {})
            records = outputs.get("record", {}).get("avatar_studio", [])
            if records:
                task_id = records[0].get("task_id") or task_id
            success = history.get("status", {}).get("status_str") == "success"
            return {
                "state": "finished" if success else "failed",
                "outputs": outputs.get("save", {}),
                "task_id": task_id,
            }
        running, pending = self.server.prompt_queue.get_current_queue()
        if any(item[1] == job["prompt_id"] for item in running):
            return {"state": "running", "task_id": task_id}
        if any(item[1] == job["prompt_id"] for item in pending):
            return {"state": "queued", "task_id": task_id}
        return {"state": "missing", "task_id": task_id}

    def output_path(self, job, output):
        if output.get("type") != "output":
            raise StudioError("The workflow did not return a saved output.")
        root = Path(self.paths.get_output_directory()).resolve()
        path = (root / output.get("subfolder", "") / output.get("filename", "")).resolve()
        expected = root / "byteplus_avatar_studio" / job["project_id"]
        if not path.is_relative_to(expected) or not path.name.startswith(job["id"]) or not path.is_file():
            raise StudioError("The workflow output is missing or outside its project.")
        return path
