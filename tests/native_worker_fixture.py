import asyncio
import base64
import importlib
import json
import os
import socket
import sys
import time
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SETTINGS = {
    "BYTEPLUS_API_KEY": "synthetic-native-modelark",
    "BYTEPLUS_SEED_SPEECH_API_KEY": "synthetic-native-speech",
    "BYTEPLUS_REGION": "ap-southeast-1",
}
BARRIER_TIMEOUT = 60
IMAGE_URL = "https://native-fixture.invalid/portrait.png"


def block_network(event, arguments):
    if event in {
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
    } or (event == "socket.__new__" and arguments[1] in {socket.AF_INET, socket.AF_INET6}):
        raise AssertionError(f"Network is disabled in the native worker: {event}")


def enter_provider(root, kind):
    import comfy.model_management

    assert not comfy.model_management.processing_interrupted()
    marker = root / f"{kind}.entered"
    with marker.open("x") as output:
        output.write(str(os.getpid()))


def leave_provider(root, kind):
    import comfy.model_management

    assert not comfy.model_management.processing_interrupted()
    (root / f"{kind}.released").touch(exist_ok=False)


def image_response(root, **request):
    assert request["response_format"] == "url"
    assert request["size"] == "864x1152"
    assert request["prompt"]
    assert request["image"].startswith("data:image/jpeg;base64,")
    enter_provider(root, "image")
    deadline = time.monotonic() + BARRIER_TIMEOUT
    while not (root / "release").is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Image provider barrier was not released.")
        time.sleep(0.02)
    leave_provider(root, "image")
    return SimpleNamespace(data=[SimpleNamespace(url=IMAGE_URL)], model=request["model"], created=0)


def ark_client(root, *, api_key, base_url, **kwargs):
    assert api_key == SETTINGS["BYTEPLUS_API_KEY"]
    assert base_url.startswith("https://")
    return SimpleNamespace(images=SimpleNamespace(generate=partial(image_response, root)))


async def image_tensor(session, url):
    import torch

    assert url == IMAGE_URL
    return torch.tensor([0.25, 0.5, 0.75]).expand(1, 1152, 864, 3).clone()


async def speech_response(root, response_class, method, url, headers, body, timeout):
    assert method == "POST"
    assert headers["X-Api-Key"] == SETTINGS["BYTEPLUS_SEED_SPEECH_API_KEY"]
    assert body["model"] == "seed-audio-1.0"
    assert body["audio_config"]["format"] == "wav"
    assert body["audio_config"]["sample_rate"] == 24000
    assert body["text_prompt"] and "@Audio1" not in body["text_prompt"]
    assert not body.get("references")
    enter_provider(root, "audio")
    deadline = time.monotonic() + BARRIER_TIMEOUT
    while not (root / "release").is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Audio provider barrier was not released.")
        await asyncio.sleep(0.02)
    leave_provider(root, "audio")
    audio = base64.b64encode((root / "approved.wav").read_bytes()).decode("ascii")
    return response_class(200, {}, json.dumps({"code": 0, "audio": audio}).encode())


async def bootstrap(payload, *, load, patches):
    assert set(payload) == {"graph", "settings", "core", "companion", "input", "output", "workspace"}
    assert payload["settings"]
    assert all(SETTINGS.get(name) == value for name, value in payload["settings"].items())
    assert not any(
        marker in name.upper()
        for name in os.environ
        for marker in ("API_KEY", "TOKEN", "SECRET", "ACCESS_KEY", "ACCESSKEY")
    )
    runner = await load(payload)
    root = Path(payload["input"])
    assert Path(runner.nodes.__file__).resolve().parent == Path(payload["core"]).resolve()
    package = runner.nodes.NODE_CLASS_MAPPINGS["BytePlusSeedream"].__module__.rsplit(".", 1)[0]
    shared = importlib.import_module(f"{package}.nodes_shared")
    images = importlib.import_module(f"{package}.seedream_utils")
    speech = importlib.import_module(f"{package}.speech_api")
    assert shared.__file__ is not None
    assert Path(shared.__file__).resolve().parents[1] == Path(payload["companion"]).resolve()
    patches.enter_context(patch.object(shared, "Ark", partial(ark_client, root)))
    patches.enter_context(patch.object(images, "download_url_to_image_tensor_async", image_tensor))
    patches.enter_context(patch.object(speech, "_send", partial(speech_response, root, speech.SpeechResponse)))
    return runner


def main():
    sys.addaudithook(block_network)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from avatar_studio import preparation_worker

    with ExitStack() as patches:
        fixture = partial(bootstrap, load=preparation_worker.bootstrap, patches=patches)
        patches.enter_context(patch.object(preparation_worker, "bootstrap", fixture))
        preparation_worker.main()


if __name__ == "__main__":
    main()
