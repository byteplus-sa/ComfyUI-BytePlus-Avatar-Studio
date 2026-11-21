import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from avatar_studio.bridge import ComfyBridge
from avatar_studio.preparation import validate_preparation
from avatar_studio.preparation_process import PreparationProcess
from avatar_studio.service import StudioService
from avatar_studio.store import Store, StudioError
from avatar_studio.workflows import build_workflow
from native_worker_fixture import SETTINGS

WORKER_TIMEOUT = 90
POLLING_WINDOW = 1.2


def process_for(core, companion, root):
    output = root / "output"
    output.mkdir()
    return PreparationProcess(core, companion, root, output, lambda name: SETTINGS[name])


def preparation_graph(project, kind, job_id):
    return build_workflow(
        project,
        {"kind": kind, "id": job_id, "project_id": "native-process"},
        {"reference": "approved.png"} if kind == "image" else {},
    )


async def await_barriers(root, jobs, interrupted):
    import comfy.model_management

    async def wait():
        while True:
            assert comfy.model_management.processing_interrupted() is interrupted, "Parent interrupt was consumed."
            for kind, task in jobs.items():
                if task.done():
                    task.result()
                    raise AssertionError(f"{kind} finished before both provider barriers were released.")
            if all((root / f"{kind}.entered").is_file() for kind in jobs):
                return
            await asyncio.sleep(0.02)

    await asyncio.wait_for(wait(), timeout=WORKER_TIMEOUT)
    process_ids = {int((root / f"{kind}.entered").read_text()) for kind in jobs}
    assert len(process_ids) == len(jobs) and os.getpid() not in process_ids
    deadline = asyncio.get_running_loop().time() + POLLING_WINDOW
    while asyncio.get_running_loop().time() < deadline:
        assert comfy.model_management.processing_interrupted() is interrupted, "Parent interrupt was consumed."
        assert not any(task.done() for task in jobs.values()), "A worker stopped during real interrupt polling."
        assert not list(root.glob("*.released"))
        await asyncio.sleep(0.02)


def verify_saved_media(root, results):
    import av

    paths = {}
    for kind, result in results.items():
        key = "images" if kind == "image" else "audio"
        assert len(result[key]) == 1
        saved = result[key][0]
        assert saved["type"] == "output"
        path = (root / "output" / saved["subfolder"] / saved["filename"]).resolve()
        assert path.is_relative_to((root / "output").resolve())
        assert path.is_file() and path.stat().st_size > 0
        assert (root / f"{kind}.released").is_file()
        paths[kind] = path
    if "image" in paths:
        with Image.open(paths["image"]) as image:
            image.load()
            assert image.size == (864, 1152)
            assert image.getpixel((0, 0)) == (63, 127, 191)
    if "audio" in paths:
        with av.open(str(paths["audio"])) as audio:
            stream = audio.streams.audio[0]
            assert stream.sample_rate == 24000
            frames = list(audio.decode(stream))
            assert sum(frame.samples for frame in frames) == 96000
            assert any(frame.to_ndarray().any() for frame in frames)


async def verify_parallel_processes(
    core, companion, input_directory, project, *, interrupted, kinds=("image", "audio")
):
    import comfy.model_management

    previous_interrupt = comfy.model_management.processing_interrupted()
    with tempfile.TemporaryDirectory(prefix="native-process-", dir=input_directory) as directory:
        root = Path(directory)
        for name in ("approved.png", "approved.wav"):
            shutil.copyfile(input_directory / name, root / name)
        runner = process_for(core, companion, root)
        jobs = {}
        try:
            comfy.model_management.interrupt_current_processing(interrupted)
            for kind in kinds:
                graph = preparation_graph(project, kind, f"subprocess-{kind}")
                jobs[kind] = asyncio.create_task(runner.run(graph))
            await await_barriers(root, jobs, interrupted)
            assert not list((root / "output").rglob("*")), "A saver ran before the provider release."
            (root / "release").touch()
            results = await asyncio.wait_for(asyncio.gather(*jobs.values()), timeout=WORKER_TIMEOUT)
            assert comfy.model_management.processing_interrupted() is interrupted, "Parent interrupt was consumed."
            verify_saved_media(root, dict(zip(jobs, results, strict=True)))
        finally:
            (root / "release").touch(exist_ok=True)
            for task in jobs.values():
                if not task.done():
                    task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(*jobs.values(), return_exceptions=True), timeout=15)
            finally:
                comfy.model_management.interrupt_current_processing(previous_interrupt)


async def verify_direct_validation(nodes, project):
    invalid = {**project, "script": "Read this in the voice of @Audio1."}
    graph = preparation_graph(invalid, "audio", "invalid-narration")
    try:
        validate_preparation(nodes, graph)
    except StudioError as error:
        assert error.status == 422
        assert "audio-reference" in str(error)
    else:
        raise AssertionError("Text-only @Audio1 narration passed native validation.")
    corrected = preparation_graph(project, "audio", "corrected-narration")
    validate_preparation(nodes, corrected)


async def verify_failed_startup_is_editable(core, companion, input_directory, server, project):
    with tempfile.TemporaryDirectory(prefix="native-invalid-", dir=input_directory) as directory:
        root = Path(directory)
        runner = process_for(core, companion, root)
        bridge = ComfyBridge(server)
        bridge.preparation = runner
        store = Store(root / "store")
        service = StudioService(store, bridge)
        owner = "native-process"
        try:
            current = store.create(owner)
            current = store.update(
                owner,
                current["id"],
                current["revision"],
                {**project, "script": "Read this in the voice of @Audio1."},
            )
            job, created = store.begin_job(owner, current["id"], current["revision"], "audio", str(uuid4()))
            assert created
            job = store.update_job(job["id"], runner="preparation", state="running")
            graph = build_workflow(current, job, {})
            await asyncio.wait_for(bridge._prepare(graph, job["prompt_id"]), timeout=WORKER_TIMEOUT)
            assert bridge.inspect(job) == {"state": "failed"}, "Startup rejection must be definite, not unknown."
            assert not list(root.glob("*.entered")), "Invalid narration reached a provider."
            assert not list((root / "output").rglob("*")), "Invalid narration reached a saver."
            await service.tick(job)
            assert store.job(owner, job["id"])["state"] == "failed"
            current = store.get(owner, current["id"])
            edited = store.update(owner, current["id"], current["revision"], {"script": project["script"]})
            assert edited["script"] == project["script"]
            assert edited["revision"] == current["revision"] + 1
            assert not store.pending_jobs()
        finally:
            await service.close()


async def verify_preparation_processes(core, companion, nodes, folder_paths, server, project):
    input_directory = Path(folder_paths.get_input_directory())
    fixture = Path(__file__).with_name("native_worker_fixture.py")
    cases = [
        (
            "parallel provider boundaries and real savers",
            lambda: verify_parallel_processes(core, companion, input_directory, project, interrupted=False),
        ),
        (
            "parent interrupt remains set during image execution and polling",
            lambda: verify_parallel_processes(
                core,
                companion,
                input_directory,
                project,
                interrupted=True,
                kinds=("image",),
            ),
        ),
        (
            "parent interrupt remains set during audio execution and polling",
            lambda: verify_parallel_processes(
                core,
                companion,
                input_directory,
                project,
                interrupted=True,
                kinds=("audio",),
            ),
        ),
        ("direct text-only narration validation", lambda: verify_direct_validation(nodes, project)),
        (
            "worker startup failure remains editable",
            lambda: verify_failed_startup_is_editable(core, companion, input_directory, server, project),
        ),
    ]
    failures = []
    with patch.object(PreparationProcess, "script", fixture):
        for name, verify in cases:
            try:
                await verify()
            except Exception as error:
                failures.append(f"{name}: {type(error).__name__}: {error}")
                print(f"FAIL native process: {failures[-1]}")
            else:
                print(f"PASS native process: {name}")
    if failures:
        raise AssertionError("Native preparation regressions:\n" + "\n".join(failures))
