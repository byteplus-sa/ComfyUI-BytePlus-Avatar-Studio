import asyncio
from pathlib import Path
from unittest.mock import patch

from avatar_studio.preparation import PreparationRunner
from avatar_studio.workflows import build_workflow


async def verify_parallel_preparation(nodes, execution, folder_paths, project):
    import torch
    from comfy_api.latest import io

    entered = {"image": asyncio.Event(), "audio": asyncio.Event()}
    release = asyncio.Event()
    image_node = nodes.NODE_CLASS_MAPPINGS["BytePlusSeedream"]
    audio_node = nodes.NODE_CLASS_MAPPINGS["BytePlusSeedAudio"]

    async def image_execute(cls, prompt, model):
        assert model["model"] == "seedream 5.5"
        assert model["images"]["image_1"].shape == (1, 500, 400, 3)
        assert cls.hidden.unique_id is None
        assert cls.hidden.prompt
        entered["image"].set()
        await release.wait()
        return io.NodeOutput(torch.zeros(1, 500, 400, 3), "[]", torch.zeros(1, 500, 400))

    async def audio_execute(cls, text_prompt, reference_mode, **kwargs):
        assert reference_mode["reference_mode"] == "text only"
        assert kwargs["generation_count"] == 1
        assert cls.hidden.unique_id is None
        entered["audio"].set()
        await release.wait()
        audio = {
            "waveform": torch.sin(torch.arange(96000, dtype=torch.float32) * 0.05).reshape(1, 1, -1) * 0.2,
            "sample_rate": 24000,
        }
        return io.NodeOutput([audio], ["{}"], [""], [4.0], [""])

    runner = PreparationRunner(nodes, execution)
    jobs = []
    with (
        patch.object(image_node, "execute", classmethod(image_execute)),
        patch.object(audio_node, "execute", classmethod(audio_execute)),
    ):
        for kind in ("image", "audio"):
            graph = build_workflow(
                project,
                {"kind": kind, "id": f"parallel-{kind}", "project_id": "native-check"},
                {"reference": "approved.png"} if kind == "image" else {},
            )
            jobs.append(asyncio.create_task(runner.run(graph)))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), timeout=10)
        finally:
            release.set()
        results = await asyncio.gather(*jobs)
    for kind, output in zip(("images", "audio"), results, strict=True):
        saved = output[kind][0]
        path = Path(folder_paths.get_output_directory()) / saved["subfolder"] / saved["filename"]
        assert path.is_file()
        assert path.stat().st_size > 0
    print("PASS native parallel preparation: both providers entered before either completed; real media savers passed")
