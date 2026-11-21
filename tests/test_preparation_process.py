import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

from avatar_studio.preparation_process import PreparationProcess
from avatar_studio.store import StudioError


class PreparationProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runner = PreparationProcess(
            self.root,
            self.root,
            self.root,
            self.root,
            lambda name: "private-fixture-value" if name == "BYTEPLUS_SEED_SPEECH_API_KEY" else "",
        )
        self.script = Path(__file__).with_name("preparation_worker_fixture.py")

    def graph(self, prompt="success"):
        return {
            "generate": {"class_type": "BytePlusSeedAudio", "inputs": {"text_prompt": prompt}},
            "save": {"class_type": "SaveAudio", "inputs": {}},
        }

    async def test_worker_receives_only_stage_credentials_through_stdin(self):
        with (
            patch.object(self.runner, "script", self.script),
            patch.dict(os.environ, {"UNRELATED_API_KEY": "not-for-worker", "BYTEPLUS_CV_API_KEY": "not-for-worker"}),
        ):
            result = await self.runner.run(self.graph())
        self.assertEqual(result, {"audio": [{"filename": "fixture.wav", "type": "output"}]})

    async def test_two_workers_start_before_either_is_released(self):
        with patch.object(self.runner, "script", self.script):
            tasks = [asyncio.create_task(self.runner.run(self.graph(name))) for name in ("first", "second")]
            try:
                async with asyncio.timeout(10):
                    while not all((self.root / name).exists() for name in ("first", "second")):
                        await asyncio.sleep(0.02)
                self.assertFalse(any(task.done() for task in tasks))
            finally:
                (self.root / "release").touch()
                await asyncio.gather(*tasks)

    async def test_cancellation_terminates_the_worker_without_retry(self):
        with patch.object(self.runner, "script", self.script):
            task = asyncio.create_task(self.runner.run(self.graph("cancel")))
            async with asyncio.timeout(10):
                while not (self.root / "cancel").exists():
                    await asyncio.sleep(0.02)
            pid = int((self.root / "cancel").read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertEqual(len(list(self.root.glob("cancel"))), 1)

    async def test_pre_execution_failure_is_definite_but_unknown_result_remains_uncertain(self):
        for prompt, expected in (("failed", StudioError), ("unknown", RuntimeError), ("malformed", RuntimeError)):
            with self.subTest(prompt=prompt), patch.object(self.runner, "script", self.script):
                with self.assertRaises(expected) as caught:
                    await self.runner.run(self.graph(prompt))
                self.assertNotIn("private-fixture-value", str(caught.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX parent-termination probe")
    async def test_worker_exits_when_its_parent_is_killed(self):
        parent = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("preparation_parent_fixture.py")),
            str(self.root),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        pid = None
        try:
            async with asyncio.timeout(10):
                while not (self.root / "cancel").exists():
                    await asyncio.sleep(0.02)
            pid = int((self.root / "cancel").read_text())
            parent.kill()
            await parent.wait()
            async with asyncio.timeout(3):
                while True:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    status = Path(f"/proc/{pid}/stat")
                    if status.is_file() and status.read_text().split(") ", 1)[1].startswith("Z "):
                        break
                    await asyncio.sleep(0.02)
            pid = None
        finally:
            if parent.returncode is None:
                parent.kill()
                await parent.wait()
            if pid is not None:
                with suppress(ProcessLookupError):
                    os.kill(pid, 9)

    async def test_missing_executable_fails_before_any_submission(self):
        with (
            patch("avatar_studio.preparation_process.asyncio.create_subprocess_exec", side_effect=OSError("private")),
            self.assertRaises(StudioError) as caught,
        ):
            await self.runner.run(self.graph())
        self.assertNotIn("private", str(caught.exception))

    async def test_video_and_mixed_graphs_never_launch_a_worker(self):
        for graph in ({}, {"generate": {"class_type": "BytePlusSeedAudio"}, "save": {"class_type": "SaveVideo"}}):
            with (
                self.subTest(graph=graph),
                patch("avatar_studio.preparation_process.asyncio.create_subprocess_exec") as spawn,
                self.assertRaises(StudioError),
            ):
                await self.runner.run(graph)
            spawn.assert_not_called()

    def test_protocol_rejects_unexpected_states_and_payloads(self):
        for result in (None, [], {}, {"state": "running"}, {"state": "finished", "outputs": None}):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                self.runner.result(json.dumps(result).encode(), 0)


if __name__ == "__main__":
    unittest.main()
