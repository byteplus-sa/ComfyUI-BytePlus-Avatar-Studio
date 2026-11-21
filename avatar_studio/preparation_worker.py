import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace


async def bootstrap(payload):
    core = Path(payload["core"]).resolve()
    workspace = Path(payload["workspace"]).resolve()
    sys.path[:0] = [str(core), str(Path(__file__).resolve().parents[1])]
    sys.argv = ["avatar-preparation", "--cpu", "--base-directory", str(workspace)]
    import comfy.options

    comfy.options.enable_args_parsing()
    import execution
    import folder_paths
    import nodes
    from aiohttp import web
    from app.node_replace_manager import NodeReplaceManager
    from server import PromptServer

    from avatar_studio.preparation import PreparationRunner, validate_preparation
    from avatar_studio.preparation_process import PREPARATION_KEYS

    allowed = {*PREPARATION_KEYS.values(), "BYTEPLUS_REGION"}
    settings = payload["settings"]
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("Invalid worker settings.")
    for name, value in settings.items():
        if not isinstance(value, str):
            raise ValueError("Invalid worker setting.")
        os.environ[name] = value
    user = workspace / "user"
    user.mkdir(parents=True, exist_ok=True)
    folder_paths.set_user_directory(str(user))
    folder_paths.set_input_directory(payload["input"])
    folder_paths.set_output_directory(payload["output"])
    folder_paths.set_temp_directory(str(workspace / "temp"))
    server = SimpleNamespace(
        routes=web.RouteTableDef(),
        app=web.Application(),
        node_replace_manager=NodeReplaceManager(),
        send_sync=lambda *args: None,
        queue_updated=lambda: None,
    )
    PromptServer.instance = server
    server.prompt_queue = execution.PromptQueue(server)
    if not await nodes.load_custom_node(str(core / "comfy_extras/nodes_audio.py")):
        raise RuntimeError("Core audio nodes are unavailable.")
    if not await nodes.load_custom_node(payload["companion"]):
        raise RuntimeError("Companion nodes are unavailable.")
    graph = payload["graph"]
    validate_preparation(nodes, graph)
    return PreparationRunner(nodes, execution)


async def execute(payload):
    try:
        runner = await bootstrap(payload)
    except Exception:
        return {"state": "failed"}
    try:
        return {"state": "finished", "outputs": await runner.run(payload["graph"])}
    except BaseException:
        return {"state": "unknown"}


def watch_parent():
    os.read(sys.stdin.fileno(), 1)
    os._exit(1)


def main():
    output = os.dup(sys.stdout.fileno())
    with open(os.devnull, "w") as silent:
        os.dup2(silent.fileno(), sys.stdout.fileno())
    try:
        payload = json.loads(sys.stdin.buffer.readline(64 * 1024))
        threading.Thread(target=watch_parent, daemon=True).start()
        result = asyncio.run(execute(payload))
    except BaseException:
        result = {"state": "unknown"}
    try:
        os.write(output, json.dumps(result).encode())
    finally:
        os.close(output)


if __name__ == "__main__":
    main()
