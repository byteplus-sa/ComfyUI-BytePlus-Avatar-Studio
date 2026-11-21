import asyncio
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from .preparation import preparation_kind
from .store import StudioError

WORKER_ENVIRONMENT = {
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
}
PREPARATION_KEYS = {"image": "BYTEPLUS_API_KEY", "audio": "BYTEPLUS_SEED_SPEECH_API_KEY"}


class PreparationProcess:
    script = Path(__file__).with_name("preparation_worker.py")

    def __init__(self, core, companion, input_directory, output_directory, get_setting):
        self.core = str(core)
        self.companion = str(companion)
        self.input = str(input_directory)
        self.output = str(output_directory)
        self.get_setting = get_setting

    async def run(self, graph):
        kind = preparation_kind(graph)
        if not kind:
            raise StudioError("Only preparation workflows can run in an isolated worker.")
        settings = {name: self.get_setting(name) for name in (PREPARATION_KEYS[kind], "BYTEPLUS_REGION")}
        environment = {name: value for name, value in os.environ.items() if name.upper() in WORKER_ENVIRONMENT}
        environment.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        with tempfile.TemporaryDirectory(prefix="avatar-preparation-") as directory:
            payload = {
                "graph": graph,
                "settings": settings,
                "core": self.core,
                "companion": self.companion,
                "input": self.input,
                "output": self.output,
                "workspace": directory,
            }
            launch = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-u",
                    str(self.script),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=environment,
                    cwd=directory,
                )
            )
            try:
                process = await asyncio.shield(launch)
            except asyncio.CancelledError:
                process = await launch
                await self.stop(process)
                raise
            except OSError:
                raise StudioError("Could not start the local preparation worker.", 503) from None
            communication = asyncio.create_task(self.exchange(process, payload))
            try:
                output = await asyncio.shield(communication)
            except BaseException:
                await self.stop(process)
                with suppress(Exception):
                    await communication
                raise
            return self.result(output, process.returncode)

    @staticmethod
    async def exchange(process, payload):
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(json.dumps(payload).encode() + b"\n")
            await process.stdin.drain()
            output = bytearray()
            while chunk := await process.stdout.read(4096):
                output.extend(chunk)
                if len(output) > 64 * 1024:
                    raise RuntimeError("Preparation worker returned too much data.")
            await process.wait()
            return bytes(output)
        finally:
            process.stdin.close()

    @staticmethod
    async def stop(process):
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()

    @staticmethod
    def result(output, returncode):
        if returncode != 0 or len(output) > 64 * 1024:
            raise RuntimeError("Preparation worker exited without a confirmed result.")
        try:
            result = json.loads(output)
        except (ValueError, UnicodeDecodeError):
            raise RuntimeError("Preparation worker returned an invalid result.") from None
        if not isinstance(result, dict):
            raise RuntimeError("Preparation worker returned an invalid result.")
        if result.get("state") == "failed":
            raise StudioError("Local preparation validation or worker setup failed. Review inputs and try again.")
        outputs = result.get("outputs")
        if result.get("state") != "finished" or not isinstance(outputs, dict):
            raise RuntimeError("Preparation stopped without a confirmed result.")
        return outputs
