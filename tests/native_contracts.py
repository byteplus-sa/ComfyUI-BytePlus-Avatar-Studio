import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from PIL import Image

from avatar_studio.workflows import build_workflow


async def verify(core, companion, studio):
    with tempfile.TemporaryDirectory(prefix="avatar-native-contracts-") as directory:
        sys.path.insert(0, str(core))
        sys.argv = ["native_contracts", "--cpu", "--base-directory", directory]
        import comfy.options

        comfy.options.enable_args_parsing()
        import execution
        import folder_paths
        import nodes
        from app.node_replace_manager import NodeReplaceManager
        from server import PromptServer

        server = SimpleNamespace(
            routes=web.RouteTableDef(),
            app=web.Application(),
            node_replace_manager=NodeReplaceManager(),
            send_sync=lambda *args: None,
        )
        PromptServer.instance = server
        server.prompt_queue = execution.PromptQueue(server)
        folder_paths.set_input_directory(str(Path(directory) / "input"))
        folder_paths.set_output_directory(str(Path(directory) / "output"))
        folder_paths.set_user_directory(str(Path(directory) / "user"))
        await nodes.init_builtin_extra_nodes()
        if not await nodes.load_custom_node(str(companion)):
            raise RuntimeError("Could not load the companion.")
        if not await nodes.load_custom_node(str(studio)):
            raise RuntimeError("Could not load Avatar Studio.")
        input_dir = Path(folder_paths.get_input_directory())
        input_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (400, 500)).save(input_dir / "approved.png")
        from test_media import write_audio

        write_audio(input_dir / "approved.wav", seconds=4, rate=24000, channels=1)
        project = {
            "character_prompt": "A fictional presenter",
            "ratio": "3:4",
            "script": "Hello and welcome to our studio.",
            "voice_direction": "Warm and natural.",
            "language": "English",
            "enable_watermark": True,
            "motion_prompt": "",
        }
        for case in ("image", "reference", "audio", "video", "recovery"):
            kind = "image" if case == "reference" else "video" if case == "recovery" else case
            job: dict[str, str | bool] = {"kind": kind, "id": case, "project_id": "native-check"}
            sources = {"image": "approved.png", "audio": "approved.wav"}
            if case == "reference":
                sources["reference"] = "approved.png"
            if case == "recovery":
                job.update(recovering=True, task_id="1234567890")
            graph = build_workflow(project, job, sources)
            result = await execution.validate_prompt(case, graph, None)
            if not result[0] or result[3] or "save" not in result[2]:
                raise AssertionError(f"Invalid {case} workflow: {result[1:4]}")
            print(f"PASS native workflow validation: {case}")
        from native_preparation import verify_parallel_preparation
        from native_process import verify_preparation_processes

        try:
            await verify_parallel_preparation(nodes, execution, folder_paths, project)
            await verify_preparation_processes(core, companion, nodes, folder_paths, server, project)
        finally:
            for callback in server.app.on_cleanup:
                await callback(server.app)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate native workflows without submitting or billing any request.")
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--companion-root", type=Path, required=True)
    parser.add_argument("--studio-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    for variable in ("BYTEPLUS_API_KEY", "ARK_API_KEY", "BYTEPLUS_SEED_SPEECH_API_KEY", "BYTEPLUS_CV_API_KEY"):
        os.environ.pop(variable, None)
    asyncio.run(verify(args.comfy_root.resolve(), args.companion_root.resolve(), args.studio_root.resolve()))
