import asyncio
import unittest
from threading import RLock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from avatar_studio.bridge import ComfyBridge
from avatar_studio.store import StudioError


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self, validation):
        bridge = ComfyBridge.__new__(ComfyBridge)
        bridge.server = SimpleNamespace(number=0, prompt_queue=Mock())
        bridge.server.prompt_queue.mutex = RLock()
        bridge.server.prompt_queue.get_current_queue.return_value = ([], [])

        async def validate(prompt_id, prompt, targets):
            return validation

        bridge.execution = SimpleNamespace(validate_prompt=validate)
        return bridge

    async def test_partial_validation_cannot_submit_paid_generation_without_its_saver(self):
        bridge = self.bridge((True, None, ["record"], {"save": {"errors": ["invalid input"]}}))
        with self.assertRaises(StudioError):
            await bridge.submit({}, "operation", {}, "default")
        bridge.server.prompt_queue.put.assert_not_called()

    async def test_sensitive_upload_key_is_separate_from_saved_prompt_metadata(self):
        bridge = self.bridge((True, None, ["save"], {}))
        await bridge.submit({}, "operation", {"api_key_comfy_org": "noncredential-fixture"}, "default")
        queued = bridge.server.prompt_queue.put.call_args.args[0]
        self.assertNotIn("api_key_comfy_org", queued[3])
        self.assertEqual(queued[5]["api_key_comfy_org"], "noncredential-fixture")
        self.assertEqual(bridge.server.number, 1)

    async def test_oauth_is_excluded_from_saved_workflow_and_extra_metadata(self):
        bridge = self.bridge((True, None, ["save"], {}))
        await bridge.submit({}, "operation", {"auth_token_comfy_org": "synthetic-oauth-token"}, "default")
        queued = bridge.server.prompt_queue.put.call_args.args[0]
        self.assertEqual(queued[2], {})
        self.assertNotIn("auth_token_comfy_org", queued[3])
        self.assertEqual(queued[5], {"auth_token_comfy_org": "synthetic-oauth-token"})

    async def test_login_messages_target_only_the_connected_source_client(self):
        bridge = ComfyBridge.__new__(ComfyBridge)
        bridge.server = SimpleNamespace(
            sockets={"source": SimpleNamespace(closed=False), "closed": SimpleNamespace(closed=True)},
            send_sync=Mock(),
        )
        bridge.send_login_request("source", {"request_id": "fixture"})
        bridge.server.send_sync.assert_called_once_with("byteplus_avatar_login", {"request_id": "fixture"}, "source")
        for client in ("closed", "missing"):
            with self.assertRaises(StudioError):
                bridge.send_login_request(client, {})

    async def test_oauth_rejects_busy_queue_before_retaining_token_or_submitting(self):
        for state in (([("running",)], []), ([], [("queued",)])):
            bridge = self.bridge((True, None, ["save"], {}))
            bridge.server.prompt_queue.get_current_queue.return_value = state
            with self.subTest(state=state), self.assertRaises(StudioError) as caught:
                await bridge.submit({}, "operation", {"auth_token_comfy_org": "synthetic-token"}, "default")
            self.assertEqual(caught.exception.status, 409)
            self.assertIn("wait", str(caught.exception).lower())
            self.assertNotIn("synthetic-token", str(caught.exception))
            bridge.server.prompt_queue.put.assert_not_called()
            self.assertEqual(bridge.server.number, 0)

    async def test_explicit_api_key_can_queue_behind_other_work(self):
        bridge = self.bridge((True, None, ["save"], {}))
        bridge.server.prompt_queue.get_current_queue.return_value = ([("running",)], [])
        await bridge.submit({}, "operation", {"api_key_comfy_org": "synthetic-key"}, "default")
        bridge.server.prompt_queue.put.assert_called_once()

    async def test_oauth_checks_queue_after_async_validation_finishes(self):
        bridge = self.bridge((True, None, ["save"], {}))

        async def validate(prompt_id, prompt, targets):
            bridge.server.prompt_queue.get_current_queue.return_value = ([("racing-job",)], [])
            return True, None, ["save"], {}

        bridge.execution.validate_prompt = validate
        with self.assertRaises(StudioError):
            await bridge.submit({}, "operation", {"auth_token_comfy_org": "synthetic-token"}, "default")
        bridge.server.prompt_queue.put.assert_not_called()

    async def test_missing_credential_cancellation_keeps_failure_explicit_and_redacted(self):
        bridge = ComfyBridge.__new__(ComfyBridge)
        api = SimpleNamespace(
            get_omnihuman_client=Mock(), cancel_task=AsyncMock(side_effect=RuntimeError("private-fixture"))
        )
        bridge.companion_module = Mock(return_value=api)
        with self.assertRaises(StudioError) as caught:
            await bridge.cancel_task("original-task")
        self.assertNotIn("private-fixture", str(caught.exception))

    async def test_preparation_jobs_overlap_without_using_the_global_queue(self):
        bridge = self.bridge((True, None, ["save"], {}))
        bridge.preparations = {}
        bridge.preparation_tasks = {}
        started = {"image": asyncio.Event(), "audio": asyncio.Event()}
        release = {"image": asyncio.Event(), "audio": asyncio.Event()}

        async def run(graph):
            kind = "image" if graph["generate"]["class_type"] == "BytePlusSeedream" else "audio"
            started[kind].set()
            await release[kind].wait()
            if kind == "image":
                raise RuntimeError("private-provider-error")
            return {"audio": [{"filename": "narration.flac"}]}

        bridge.preparation = SimpleNamespace(run=AsyncMock(side_effect=run))
        for kind, provider, saver in (
            ("image", "BytePlusSeedream", "SaveImage"),
            ("audio", "BytePlusSeedAudio", "SaveAudio"),
        ):
            graph = {"generate": {"class_type": provider, "inputs": {}}, "save": {"class_type": saver, "inputs": {}}}
            await bridge.submit(graph, kind, {}, "default")
            await bridge.submit(graph, kind, {}, "default")
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=2)
            self.assertEqual(bridge.preparation.run.await_count, 2)
            bridge.server.prompt_queue.put.assert_not_called()
            release["image"].set()
            await bridge.preparation_tasks["image"]
            self.assertEqual(bridge.inspect({"runner": "preparation", "prompt_id": "image"}), {"state": "unknown"})
            self.assertEqual(bridge.inspect({"runner": "preparation", "prompt_id": "audio"}), {"state": "running"})
            release["audio"].set()
            await bridge.preparation_tasks["audio"]
            self.assertEqual(bridge.inspect({"runner": "preparation", "prompt_id": "audio"})["state"], "finished")
            bridge.release("audio")
            self.assertNotIn("audio", bridge.preparations)
        finally:
            await bridge.close()

    async def test_preparation_shutdown_and_restart_never_resubmit_paid_work(self):
        bridge = self.bridge((True, None, ["save"], {}))
        bridge.preparations = {}
        bridge.preparation_tasks = {}

        async def pending(graph):
            await asyncio.Event().wait()

        bridge.preparation = SimpleNamespace(run=AsyncMock(side_effect=pending))
        graph = {
            "generate": {"class_type": "BytePlusSeedAudio", "inputs": {}},
            "save": {"class_type": "SaveAudio", "inputs": {}},
        }
        await bridge.submit(graph, "audio", {}, "default")
        await asyncio.sleep(0)
        await bridge.close()
        self.assertFalse(bridge.preparation_tasks)
        self.assertEqual(bridge.inspect({"runner": "preparation", "prompt_id": "audio"}), {"state": "missing"})
        bridge.preparation.run.assert_awaited_once()
        bridge.server.prompt_queue.put.assert_not_called()

    async def test_parallel_runner_rejects_mixed_workflows_before_execution(self):
        bridge = self.bridge((True, None, ["save"], {}))
        graph = {
            "generate": {"class_type": "BytePlusSeedAudio", "inputs": {}},
            "save": {"class_type": "SaveVideo", "inputs": {}},
        }
        with self.assertRaises(StudioError):
            await bridge.submit(graph, "operation", {}, "default")
        bridge.server.prompt_queue.put.assert_not_called()

    async def test_released_companion_http_400_cancel_refusal_is_not_a_server_failure(self):
        class ProviderError(Exception):
            def __init__(self, status, code):
                super().__init__(f"OmniHuman request failed (HTTP {status}, code {code}): private-fixture")
                self.status = status

        bridge = ComfyBridge.__new__(ComfyBridge)
        for status, code in ((400, 50217), (401, 50217), (400, 50510), (500, 50217)):
            api = SimpleNamespace(
                RetryableRequestError=ProviderError,
                get_text=lambda key, **values: (
                    f"OmniHuman request failed (HTTP {values['status']}, code {values['code']}): "
                ),
                get_omnihuman_client=Mock(),
                cancel_task=AsyncMock(side_effect=ProviderError(status, code)),
            )
            bridge.companion_module = Mock(return_value=api)
            if (status, code) == (400, 50217):
                self.assertFalse(await bridge.cancel_task("completed-fixture-task"))
            else:
                with self.assertRaises(StudioError) as caught:
                    await bridge.cancel_task("completed-fixture-task")
                self.assertNotIn("private-fixture", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
