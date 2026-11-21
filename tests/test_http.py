import asyncio
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import av
import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from avatar_studio.routes import PREFIX, create_routes, register
from avatar_studio.service import StudioService
from avatar_studio.store import Store, StudioError


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.bridge = Mock()
        self.bridge.setup.return_value = {
            "ready": True,
            "version": "0.10.0",
            "missing_nodes": [],
            "credentials": {"image": True, "audio": True, "video": True},
        }
        self.bridge.stage_ready.return_value = None
        self.bridge.submit = AsyncMock()
        self.bridge.source.side_effect = lambda asset, store: asset["filename"]
        self.bridge.cancel_task = AsyncMock(return_value=False)
        self.service = StudioService(self.store, self.bridge)
        self.service.start = Mock()
        app = web.Application()
        app.add_routes(
            create_routes(lambda: self.service, lambda request: request.headers.get("Comfy-User", "default"), self.root)
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        response = await self.client.post(f"{PREFIX}/api/projects", json={"title": "HTTP avatar"})
        self.project = await response.json()

    async def asyncTearDown(self):
        await self.client.close()
        await self.service.close()
        self.temp.cleanup()

    async def patch(self, **fields):
        response = await self.client.patch(
            f"{PREFIX}/api/projects/{self.project['id']}", json={"revision": self.project["revision"], "fields": fields}
        )
        self.assertEqual(response.status, 200)
        self.project = await response.json()

    async def test_create_edit_reload_and_owner_isolation_end_to_end(self):
        await self.patch(script="My exact words.", character_prompt="A fictional presenter")
        response = await self.client.get(f"{PREFIX}/api/projects/{self.project['id']}")
        self.assertEqual((await response.json())["script"], "My exact words.")
        response = await self.client.get(f"{PREFIX}/api/projects/{self.project['id']}", headers={"Comfy-User": "other"})
        self.assertEqual(response.status, 404)

    async def test_registration_accepts_the_real_comfyui_route_table_type(self):
        server = SimpleNamespace(routes=web.RouteTableDef(), app=web.Application())
        with patch.dict("sys.modules", {"folder_paths": SimpleNamespace(get_user_directory=lambda: str(self.root))}):
            register(server, self.root)
        self.assertGreater(len(server.routes), 10)

    async def test_bundled_fonts_are_served_but_arbitrary_files_are_not(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "Inter.woff2").write_bytes(b"font-test-fixture")
        (assets / "private.txt").write_text("not a public asset")
        response = await self.client.get(f"{PREFIX}/assets/Inter.woff2")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        response = await self.client.get(f"{PREFIX}/assets/private.txt")
        self.assertEqual(response.status, 404)

    async def test_cross_origin_write_is_rejected(self):
        response = await self.client.post(
            f"{PREFIX}/api/projects",
            json={"title": "Forbidden"},
            headers={"Origin": "https://untrusted.example", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(response.status, 403)

    async def test_upload_key_save_requires_explicit_consent_and_never_returns_value(self):
        endpoint = f"{PREFIX}/api/settings/upload-key"
        for remember in (None, False, "true", 1):
            response = await self.client.post(endpoint, json={"value": "noncredential-fixture", "remember": remember})
            self.assertEqual(response.status, 400)
        response = await self.client.post(endpoint, json={"value": "noncredential-fixture", "remember": True})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"configured": True})
        response = await self.client.get(endpoint)
        self.assertEqual(await response.json(), {"configured": True})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        project = await (await self.client.get(f"{PREFIX}/api/projects/{self.project['id']}")).json()
        self.assertNotIn("noncredential-fixture", json.dumps(project))

    async def test_upload_key_status_and_removal_are_owner_scoped(self):
        endpoint = f"{PREFIX}/api/settings/upload-key"
        await self.client.post(endpoint, json={"value": "default-fixture", "remember": True})
        response = await self.client.get(endpoint, headers={"Comfy-User": "other"})
        self.assertEqual(await response.json(), {"configured": False})
        await self.client.delete(endpoint, headers={"Comfy-User": "other"})
        self.assertEqual(await (await self.client.get(endpoint)).json(), {"configured": True})
        response = await self.client.delete(endpoint)
        self.assertEqual(await response.json(), {"configured": False})
        self.assertEqual(await (await self.client.get(endpoint)).json(), {"configured": False})

    async def test_upload_key_endpoints_reject_cross_origin_requests(self):
        endpoint = f"{PREFIX}/api/settings/upload-key"
        for method in ("get", "post", "delete"):
            response = await getattr(self.client, method)(
                endpoint,
                headers={"Origin": "https://untrusted.example", "Sec-Fetch-Site": "cross-site"},
            )
            self.assertEqual(response.status, 403)

    async def test_saved_upload_key_requires_explicit_selection_and_is_only_resolved_for_video(self):
        endpoint = f"{PREFIX}/api/settings/upload-key"
        await self.client.post(endpoint, json={"value": "saved-fixture", "remember": True})
        self.service.generate = AsyncMock(return_value=self.project)
        body = {"kind": "video", "revision": 0, "operation_id": str(uuid4()), "use_saved_upload_key": True}
        target = f"{PREFIX}/api/projects/{self.project['id']}/generate"
        response = await self.client.post(target, json=body)
        self.assertEqual(response.status, 202)
        self.assertEqual(self.service.generate.call_args.args[-1], {"api_key_comfy_org": "saved-fixture"})
        body["use_saved_upload_key"] = False
        response = await self.client.post(target, json=body)
        self.assertEqual(response.status, 202)
        self.assertEqual(self.service.generate.call_args.args[-1], {})
        response = await self.client.post(target, json=body, headers={"X-Comfy-Org-Api-Key": "session-fixture"})
        self.assertEqual(response.status, 202)
        self.assertEqual(self.service.generate.call_args.args[-1], {"api_key_comfy_org": "session-fixture"})
        body.update(kind="image", use_saved_upload_key=True)
        self.assertEqual((await self.client.post(target, json=body)).status, 400)

    async def test_missing_saved_key_or_conflicting_sources_never_submits_work(self):
        target = f"{PREFIX}/api/projects/{self.project['id']}/generate"
        body = {"kind": "video", "revision": 0, "operation_id": str(uuid4()), "use_saved_upload_key": True}
        response = await self.client.post(target, json=body)
        self.assertEqual(response.status, 409)
        response = await self.client.post(target, json=body, headers={"X-Comfy-Org-Api-Key": "session-fixture"})
        self.assertEqual(response.status, 400)
        self.bridge.submit.assert_not_awaited()

    async def test_invalid_json_empty_body_and_oversized_request_are_rejected(self):
        for data, expected in (("", 400), ("[]", 400), ("{", 400), ("x" * 17000, 413)):
            response = await self.client.post(f"{PREFIX}/api/projects", data=data)
            self.assertEqual(response.status, expected)

    async def test_double_submit_queues_only_one_paid_workflow(self):
        await self.patch(character_prompt="Fictional presenter")
        operation = str(uuid4())
        body = {"revision": self.project["revision"], "kind": "image", "operation_id": operation}
        for _ in range(2):
            response = await self.client.post(f"{PREFIX}/api/projects/{self.project['id']}/generate", json=body)
            self.assertEqual(response.status, 202)
        self.assertEqual(self.bridge.submit.await_count, 1)

    async def test_missing_credential_fails_before_any_queue_submission(self):
        await self.patch(character_prompt="Fictional presenter")
        self.bridge.stage_ready.side_effect = StudioError("Missing credential.", 503)
        response = await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/generate",
            json={"revision": self.project["revision"], "kind": "image", "operation_id": str(uuid4())},
        )
        self.assertEqual(response.status, 503)
        self.bridge.submit.assert_not_awaited()

    async def test_image_and_audio_accept_the_same_saved_snapshot_without_duplicate_stage_work(self):
        await self.patch(script="Welcome to our studio.", character_prompt="A fictional presenter")
        target = f"{PREFIX}/api/projects/{self.project['id']}/generate"

        def body(kind):
            return {
                "revision": self.project["revision"],
                "kind": kind,
                "operation_id": str(uuid4()),
                "generation_token": self.project["generation_tokens"][kind],
            }

        responses = await asyncio.gather(
            self.client.post(target, json=body("image")), self.client.post(target, json=body("audio"))
        )
        self.assertEqual([response.status for response in responses], [202, 202])
        self.assertEqual(self.bridge.submit.await_count, 2)
        current = self.store.get("default", self.project["id"])
        self.assertEqual({job["kind"] for job in current["jobs"]}, {"image", "audio"})
        self.assertTrue(all(job["runner"] == "preparation" for job in current["jobs"]))
        self.assertEqual((await self.client.post(target, json=body("image"))).status, 409)
        self.assertEqual(self.bridge.submit.await_count, 2)

    async def test_unknown_preparation_after_restart_is_not_requeued_or_marked_successful(self):
        await self.patch(character_prompt="A fictional presenter")
        response = await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/generate",
            json={"revision": self.project["revision"], "kind": "image", "operation_id": str(uuid4())},
        )
        project = await response.json()
        job = project["jobs"][0]
        self.bridge.inspect.return_value = {"state": "missing"}
        await self.service.tick(job)
        unresolved = self.store.job("default", job["id"])
        self.assertEqual(unresolved["state"], "unknown")
        self.assertIn("other preparation stage", unresolved["message"])
        self.assertEqual(self.bridge.submit.await_count, 1)

    def unresolved_preparation(self, kind="image"):
        project = self.store.get("default", self.project["id"])
        job, _ = self.store.begin_job("default", project["id"], project["revision"], kind, str(uuid4()))
        return self.store.update_job(job["id"], state="unknown", runner="preparation")

    async def test_resolution_requires_exact_acknowledgement_and_valid_json(self):
        job = self.unresolved_preparation()
        endpoint = f"{PREFIX}/api/jobs/{job['id']}/resolve"
        for body in ({}, *({"acknowledge": value} for value in (None, False, "true", 1, [], {}))):
            with self.subTest(body=body):
                response = await self.client.post(endpoint, json=body)
                self.assertEqual(response.status, 400)
        for data, status in (("", 400), ("[]", 400), ("{", 400), ("x" * 17000, 413)):
            with self.subTest(data=data[:20]):
                self.assertEqual((await self.client.post(endpoint, data=data)).status, status)
        self.assertEqual(self.store.job("default", job["id"]), job)
        self.bridge.inspect.assert_not_called()
        self.bridge.release.assert_not_called()
        self.bridge.submit.assert_not_awaited()

    async def test_resolution_is_owner_scoped_and_same_origin(self):
        job = self.unresolved_preparation()
        for job_id, headers, status in (
            (job["id"], {"Comfy-User": "other"}, 404),
            (job["id"], {"Sec-Fetch-Site": "cross-site"}, 403),
            (str(uuid4()), {}, 404),
            ("invalid", {}, 400),
        ):
            with self.subTest(job_id=job_id, headers=headers):
                response = await self.client.post(
                    f"{PREFIX}/api/jobs/{job_id}/resolve", json={"acknowledge": True}, headers=headers
                )
                self.assertEqual(response.status, status)
        self.assertEqual(self.store.job("default", job["id"]), job)
        self.bridge.inspect.assert_not_called()
        self.bridge.release.assert_not_called()

    async def test_resolution_dismisses_missing_or_unknown_preparation_without_provider_work(self):
        for kind, observed in (("image", "missing"), ("audio", "unknown")):
            with self.subTest(kind=kind, observed=observed):
                job = self.unresolved_preparation(kind)
                original = self.store.get("default", self.project["id"])
                self.bridge.inspect.return_value = {"state": observed}
                self.bridge.release.reset_mock()
                response = await self.client.post(
                    f"{PREFIX}/api/jobs/{job['id']}/resolve", json={"acknowledge": True}
                )
                self.assertEqual(response.status, 200)
                result = await response.json()
                resolved = next(item for item in result["jobs"] if item["id"] == job["id"])
                self.assertEqual(resolved["state"], "dismissed")
                self.assertEqual(resolved["prompt_id"], job["prompt_id"])
                self.assertIn("provider usage", resolved["message"])
                for key in ("current", "approvals", "assets", "generation_tokens"):
                    self.assertEqual(result[key], original[key])
                self.bridge.release.assert_called_once_with(job["prompt_id"])
        self.assertEqual(self.store.pending_jobs(), [])
        self.bridge.submit.assert_not_awaited()
        self.bridge.cancel_task.assert_not_awaited()
        self.bridge.stage_ready.assert_not_called()
        self.service.start.assert_not_called()
        self.bridge.inspect.reset_mock()
        with (
            patch("avatar_studio.service.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)),
            self.assertRaises(asyncio.CancelledError),
        ):
            await self.service.watch()
        self.bridge.inspect.assert_not_called()

    async def test_resolution_rejects_live_or_collectable_bridge_results(self):
        job = self.unresolved_preparation()
        for state in ("queued", "running", "finished", "failed", "unexpected", None):
            with self.subTest(state=state):
                self.bridge.inspect.return_value = {"state": state}
                response = await self.client.post(
                    f"{PREFIX}/api/jobs/{job['id']}/resolve", json={"acknowledge": True}
                )
                self.assertEqual(response.status, 409)
                self.assertEqual(self.store.job("default", job["id"]), job)
        self.bridge.release.assert_not_called()
        self.bridge.submit.assert_not_awaited()
        self.bridge.cancel_task.assert_not_awaited()

    async def test_resolution_rejects_non_preparation_jobs_and_non_unknown_states_before_inspection(self):
        job = self.unresolved_preparation()
        invalid = [
            {"kind": "video", "runner": "preparation", "state": "unknown"},
            {"kind": "image", "runner": "queue", "state": "unknown"},
            {"kind": "audio", "runner": None, "state": "unknown"},
            *(
                {"kind": "image", "runner": "preparation", "state": state}
                for state in ("preparing", "queued", "running", "failed", "done", "canceled")
            ),
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                original = self.store.update_job(job["id"], **fields)
                response = await self.client.post(
                    f"{PREFIX}/api/jobs/{job['id']}/resolve", json={"acknowledge": True}
                )
                self.assertEqual(response.status, 409)
                self.assertEqual(self.store.job("default", job["id"]), original)
        self.bridge.inspect.assert_not_called()
        self.bridge.release.assert_not_called()

    async def test_resolution_inspection_failure_keeps_the_job_unknown_and_redacts_details(self):
        job = self.unresolved_preparation()
        self.bridge.inspect.side_effect = RuntimeError("SENSITIVE_FIXTURE_DO_NOT_EXPOSE")
        response = await self.client.post(f"{PREFIX}/api/jobs/{job['id']}/resolve", json={"acknowledge": True})
        self.assertEqual(response.status, 500)
        self.assertNotIn("SENSITIVE_FIXTURE", await response.text())
        self.assertEqual(self.store.job("default", job["id"]), job)
        self.bridge.release.assert_not_called()

    async def test_resolution_is_idempotent_for_concurrent_and_repeated_requests(self):
        job = self.unresolved_preparation()
        self.bridge.inspect.return_value = {"state": "unknown"}
        endpoint = f"{PREFIX}/api/jobs/{job['id']}/resolve"
        responses = await asyncio.gather(
            self.client.post(endpoint, json={"acknowledge": True}),
            self.client.post(endpoint, json={"acknowledge": True}),
        )
        self.assertEqual([response.status for response in responses], [200, 200])
        first, second = [await response.json() for response in responses]
        self.assertEqual(first, second)
        response = await self.client.post(endpoint, json={"acknowledge": True})
        self.assertEqual(await response.json(), first)
        self.bridge.inspect.assert_called_once()
        self.bridge.release.assert_called_once_with(job["prompt_id"])
        self.bridge.submit.assert_not_awaited()
        self.bridge.cancel_task.assert_not_awaited()

    async def test_resolution_rechecks_job_state_after_acquiring_the_project_lock(self):
        job = self.unresolved_preparation()
        lock = self.service.locks.setdefault(self.project["id"], asyncio.Lock())
        async with lock:
            resolution = asyncio.create_task(self.service.resolve("default", job["id"]))
            await asyncio.sleep(0)
            self.assertFalse(resolution.done())
            self.store.update_job(job["id"], state="done")
        with self.assertRaises(StudioError) as caught:
            await resolution
        self.assertEqual(caught.exception.status, 409)
        self.bridge.inspect.assert_not_called()
        self.bridge.release.assert_not_called()
        self.assertEqual(self.store.job("default", job["id"])["state"], "done")

    async def test_resolution_checks_bridge_state_after_waiting_for_the_project_lock(self):
        job = self.unresolved_preparation()
        self.bridge.inspect.return_value = {"state": "missing"}
        lock = self.service.locks.setdefault(self.project["id"], asyncio.Lock())
        async with lock:
            resolution = asyncio.create_task(self.service.resolve("default", job["id"]))
            await asyncio.sleep(0)
            self.assertFalse(resolution.done())
            self.bridge.inspect.assert_not_called()
            self.bridge.inspect.return_value = {"state": "finished", "outputs": {"images": [{"filename": "ready.png"}]}}
        with self.assertRaises(StudioError) as caught:
            await resolution
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.store.job("default", job["id"]), job)
        self.bridge.release.assert_not_called()

    async def test_unknown_acceptance_is_not_retried_and_secret_exception_is_not_exposed(self):
        await self.patch(character_prompt="Fictional presenter")
        self.bridge.submit.side_effect = RuntimeError("SENSITIVE_FIXTURE_DO_NOT_EXPOSE")
        operation = str(uuid4())
        body = {"revision": self.project["revision"], "kind": "image", "operation_id": operation}
        response = await self.client.post(f"{PREFIX}/api/projects/{self.project['id']}/generate", json=body)
        self.assertEqual(response.status, 503)
        self.assertNotIn("SENSITIVE_FIXTURE", await response.text())
        response = await self.client.post(f"{PREFIX}/api/projects/{self.project['id']}/generate", json=body)
        self.assertEqual(response.status, 202)
        self.assertEqual(self.bridge.submit.await_count, 1)
        self.assertEqual((await response.json())["jobs"][0]["state"], "unknown")

    async def test_unapproved_video_is_rejected_by_backend_not_just_ui(self):
        response = await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/generate",
            json={"revision": 0, "kind": "video", "operation_id": str(uuid4())},
        )
        self.assertEqual(response.status, 409)
        self.bridge.submit.assert_not_awaited()

    async def test_unknown_operation_is_inspected_without_resubmission(self):
        await self.patch(character_prompt="A fictional presenter")
        job, _ = self.store.begin_job("default", self.project["id"], self.project["revision"], "image", str(uuid4()))
        self.store.update_job(job["id"], state="unknown")
        for observed, expected in (("queued", "queued"), ("missing", "unknown")):
            with self.subTest(observed=observed):
                self.store.update_job(job["id"], state="unknown")
                self.bridge.inspect.return_value = {"state": observed}
                with (
                    patch("avatar_studio.service.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)),
                    self.assertRaises(asyncio.CancelledError),
                ):
                    await self.service.watch()
                self.assertEqual(self.store.job("default", job["id"])["state"], expected)
        self.assertEqual(self.bridge.inspect.call_count, 2)
        self.bridge.submit.assert_not_awaited()

    async def test_cancellation_rechecks_state_after_waiting_for_project_lock(self):
        await self.patch(character_prompt="A fictional presenter")
        job, _ = self.store.begin_job("default", self.project["id"], self.project["revision"], "image", str(uuid4()))
        self.store.update_job(job["id"], kind="video", state="running", task_id="original-task")
        lock = self.service.locks.setdefault(self.project["id"], asyncio.Lock())
        await lock.acquire()
        cancellation = asyncio.create_task(self.service.cancel("default", job["id"]))
        await asyncio.sleep(0)
        self.store.update_job(job["id"], state="done")
        lock.release()
        with self.assertRaises(StudioError):
            await cancellation
        self.bridge.cancel_task.assert_not_awaited()
        self.assertEqual(self.store.job("default", job["id"])["state"], "done")

    async def test_reference_upload_is_decoded_and_asset_is_private(self):
        image = io.BytesIO()
        Image.new("RGB", (400, 500), (50, 90, 70)).save(image, format="PNG")
        response = await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/reference",
            data=image.getvalue(),
            headers={"X-Project-Revision": "0"},
        )
        self.assertEqual(response.status, 200)
        result = await response.json()
        url = f"{PREFIX}/api/projects/{result['id']}/assets/{result['reference_id']}"
        response = await self.client.get(url)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        response = await self.client.get(url, headers={"Comfy-User": "other"})
        self.assertEqual(response.status, 404)

    async def test_reference_upload_with_stale_revision_does_not_leave_orphan_media(self):
        await self.patch(title="Updated title")
        image = io.BytesIO()
        Image.new("RGB", (400, 500)).save(image, format="PNG")
        response = await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/reference",
            data=image.getvalue(),
            headers={"X-Project-Revision": "0"},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(list(self.store.media_dir.iterdir()), [])

    async def upload_candidate(self, kind, data, revision=None, **headers):
        return await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/candidates/{kind}",
            data=data,
            headers={"X-Project-Revision": str(self.project["revision"] if revision is None else revision), **headers},
        )

    def portrait_bytes(self):
        output = io.BytesIO()
        Image.new("RGB", (400, 500), (30, 50, 70)).save(output, format="PNG")
        return output.getvalue()

    async def test_upload_only_workflow_needs_approvals_but_no_script_or_permission_flag(self):
        from test_media import write_audio

        audio = self.root / "upload.wav"
        write_audio(audio, seconds=4)
        await self.patch(rights_confirmed=False)
        for kind, data in (("image", self.portrait_bytes()), ("audio", audio.read_bytes())):
            response = await self.upload_candidate(kind, data)
            self.assertEqual(response.status, 200)
            self.project = await response.json()
            candidate = next(asset for asset in self.project["assets"] if asset["id"] == self.project["current"][kind])
            self.assertEqual(candidate["origin"], "upload")
            self.assertIsNone(self.project["approvals"][kind])
            self.assertEqual(self.project["jobs"], [])
            response = await self.client.post(
                f"{PREFIX}/api/projects/{self.project['id']}/approve",
                json={
                    "revision": self.project["revision"],
                    "kind": kind,
                    "asset_id": candidate["id"],
                    "sha256": candidate["sha256"],
                },
            )
            self.assertEqual(response.status, 200)
            self.project = await response.json()
        self.bridge.submit.assert_not_awaited()
        self.bridge.stage_ready.assert_not_called()
        self.assertEqual(self.project["script"], "")
        self.assertEqual(self.project["character_prompt"], "")
        self.assertIsNone(self.project["reference_id"])
        response = await self.client.post(
            f"{PREFIX}/api/projects/{self.project['id']}/generate",
            json={"revision": self.project["revision"], "kind": "video", "operation_id": str(uuid4())},
            headers={"X-Comfy-Org-Api-Key": "noncredential-fixture"},
        )
        self.assertEqual(response.status, 202)
        types = {node["class_type"] for node in self.bridge.submit.call_args.args[0].values()}
        self.assertIn("BytePlusOmniHuman", types)
        self.assertNotIn("BytePlusSeedream", types)
        self.assertNotIn("BytePlusSeedAudio", types)

    async def test_candidate_upload_enforces_owner_origin_revision_and_idle_state(self):
        data = self.portrait_bytes()
        for headers, expected in (
            ({"Comfy-User": "another"}, 404),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
            ({"X-Project-Revision": "invalid"}, 400),
        ):
            response = await self.upload_candidate("image", data, **headers)
            self.assertEqual(response.status, expected)
        await self.patch(title="Changed")
        self.assertEqual((await self.upload_candidate("image", data, revision=0)).status, 409)
        self.store.begin_job("default", self.project["id"], self.project["revision"], "image", str(uuid4()))
        self.project = self.store.get("default", self.project["id"])
        self.assertEqual((await self.upload_candidate("image", data)).status, 409)
        self.assertEqual(list(self.store.media_dir.iterdir()), [])

    async def test_failed_or_stale_upload_preserves_previous_candidate_and_cleans_new_files(self):
        response = await self.upload_candidate("image", self.portrait_bytes())
        self.assertEqual(response.status, 200)
        self.project = await response.json()
        original = self.project["current"]["image"]
        self.assertEqual((await self.upload_candidate("image", b"invalid")).status, 400)
        self.assertEqual(self.store.get("default", self.project["id"])["current"]["image"], original)
        from avatar_studio import media

        prepare = media.prepare_candidate

        def concurrent_edit(*args):
            prepared = prepare(*args)
            self.store.update(
                "default", self.project["id"], self.project["revision"], {"title": "Changed during decode"}
            )
            return prepared

        with patch("avatar_studio.service.media.prepare_candidate", side_effect=concurrent_edit):
            self.assertEqual((await self.upload_candidate("image", self.portrait_bytes())).status, 409)
        self.assertEqual(len(list(self.store.media_dir.iterdir())), 1)
        self.assertEqual(self.store.get("default", self.project["id"])["current"]["image"], original)

    async def test_oversized_candidate_request_is_rejected_before_decoding(self):
        with patch("avatar_studio.routes.MAX_AUDIO_UPLOAD_BYTES", 8):
            response = await self.upload_candidate("audio", b"x" * 9)
        self.assertEqual(response.status, 413)
        self.assertEqual(list(self.store.media_dir.iterdir()), [])

    async def test_canceled_upload_waits_for_decoder_cleanup_without_committing(self):
        from avatar_studio import media

        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        prepare = media.prepare_candidate

        def delayed_prepare(*args):
            loop.call_soon_threadsafe(started.set)
            release.wait(timeout=5)
            return prepare(*args)

        with patch("avatar_studio.service.media.prepare_candidate", side_effect=delayed_prepare):
            task = asyncio.create_task(
                self.service.upload_candidate(
                    "default",
                    self.project["id"],
                    self.project["revision"],
                    "image",
                    self.portrait_bytes(),
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                task.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(list(self.store.media_dir.iterdir()), [])
        self.assertIsNone(self.store.get("default", self.project["id"])["current"]["image"])

    async def test_concurrent_uploads_accept_only_one_candidate_for_the_revision(self):
        responses = await asyncio.gather(
            self.upload_candidate("image", self.portrait_bytes()),
            self.upload_candidate("image", self.portrait_bytes()),
        )
        self.assertEqual(sorted(response.status for response in responses), [200, 409])
        self.assertEqual(len(self.store.get("default", self.project["id"])["assets"]), 1)
        self.assertEqual(len(list(self.store.media_dir.iterdir())), 1)

    async def test_canceled_reference_upload_does_not_leave_an_orphan_file(self):
        from avatar_studio import media

        started = asyncio.Event()
        finished = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        prepare = media.prepare_reference

        def delayed_prepare(*args):
            loop.call_soon_threadsafe(started.set)
            release.wait(timeout=5)
            result = prepare(*args)
            loop.call_soon_threadsafe(finished.set)
            return result

        with patch("avatar_studio.service.media.prepare_reference", side_effect=delayed_prepare):
            task = asyncio.create_task(
                self.service.reference(
                    "default",
                    self.project["id"],
                    self.project["revision"],
                    self.portrait_bytes(),
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                task.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(finished.wait(), timeout=5)
        self.assertEqual(list(self.store.media_dir.iterdir()), [])
        self.assertIsNone(self.store.get("default", self.project["id"])["reference_id"])

    async def test_failed_video_collection_keeps_the_observed_provider_task_id(self):
        job, _ = self.store.begin_job("default", self.project["id"], self.project["revision"], "image", str(uuid4()))
        self.store.update_job(job["id"], kind="video", state="running")
        source = self.root / "invalid.mp4"
        source.write_bytes(b"invalid video fixture")
        self.bridge.output_path.return_value = source
        self.bridge.inspect.return_value = {
            "state": "finished",
            "task_id": "provider-task-fixture",
            "outputs": {"videos": [{"type": "output", "filename": source.name}]},
        }
        with (
            patch("avatar_studio.service.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)),
            self.assertRaises(asyncio.CancelledError),
        ):
            await self.service.watch()
        recovered = self.store.job("default", job["id"])
        self.assertEqual(recovered["state"], "unknown")
        self.assertEqual(recovered["task_id"], "provider-task-fixture")
        self.bridge.submit.assert_not_awaited()

    async def test_recovery_collects_existing_video_without_upload_or_new_generation(self):
        job_id = str(uuid4())
        job = {
            "id": job_id,
            "project_id": self.project["id"],
            "owner": "default",
            "kind": "video",
            "state": "unknown",
            "task_id": "original-task",
            "assets": {},
        }
        with self.store.transaction():
            self.store.db.execute("INSERT INTO jobs VALUES (?,?,?)", (job_id, self.project["id"], json.dumps(job)))
        response = await self.client.post(f"{PREFIX}/api/jobs/{job_id}/recover", json={"task_id": "original-task"})
        self.assertEqual(response.status, 200)
        graph = self.bridge.submit.call_args.args[0]
        self.assertEqual(graph[f"avatar_{job_id}"]["class_type"], "BytePlusOmniHumanTaskResult")
        self.bridge.source.assert_not_called()
        response = await self.client.post(f"{PREFIX}/api/jobs/{job_id}/recover", json={"task_id": "different-task"})
        self.assertEqual(response.status, 409)

    async def test_full_review_pipeline_collects_results_and_requires_explicit_approvals(self):
        from test_media import write_audio

        await self.patch(
            script="These are the exact words.", character_prompt="A fictional presenter", rights_confirmed=True
        )
        for kind in ("image", "audio", "video"):
            project = self.store.get("default", self.project["id"])
            operation = str(uuid4())
            if kind == "video":
                saved = await self.client.post(
                    f"{PREFIX}/api/settings/upload-key",
                    json={"value": "noncredential-upload-fixture", "remember": True},
                )
                self.assertEqual(saved.status, 200)
            response = await self.client.post(
                f"{PREFIX}/api/projects/{project['id']}/generate",
                json={
                    "revision": project["revision"],
                    "kind": kind,
                    "operation_id": operation,
                    "use_saved_upload_key": kind == "video",
                },
            )
            self.assertEqual(response.status, 202)
            if kind == "video":
                self.assertEqual(
                    self.bridge.submit.call_args.args[2], {"api_key_comfy_org": "noncredential-upload-fixture"}
                )
            source = self.root / f"result.{ {'image': 'png', 'audio': 'wav', 'video': 'mp4'}[kind] }"
            if kind == "image":
                Image.new("RGB", (400, 500), (40, 80, 120)).save(source)
            elif kind == "audio":
                write_audio(source, seconds=4, rate=24000, channels=1)
            else:
                with av.open(str(source), "w") as container:
                    stream = container.add_stream("mpeg4", rate=8)
                    stream.width, stream.height, stream.pix_fmt = 400, 500, "yuv420p"
                    for _ in range(32):
                        frame = av.VideoFrame.from_ndarray(np.full((500, 400, 3), 80, dtype=np.uint8), format="rgb24")
                        for packet in stream.encode(frame):
                            container.mux(packet)
                    for packet in stream.encode():
                        container.mux(packet)
            self.bridge.output_path.return_value = source
            self.bridge.inspect.return_value = {
                "state": "finished",
                "task_id": "original-task" if kind == "video" else None,
                "outputs": {"audio" if kind == "audio" else "images": [{"type": "output", "filename": source.name}]},
            }
            await self.service.tick(self.store.job("default", operation))
            project = self.store.get("default", project["id"])
            self.assertEqual(project["jobs"][-1]["state"], "done")
            asset = self.store.asset("default", project["id"], project["current"][kind])
            if kind != "video":
                self.assertIsNone(project["approvals"][kind])
                response = await self.client.post(
                    f"{PREFIX}/api/projects/{project['id']}/approve",
                    json={
                        "revision": project["revision"],
                        "kind": kind,
                        "asset_id": asset["id"],
                        "sha256": asset["sha256"],
                    },
                )
                self.assertEqual(response.status, 200)
            else:
                response = await self.client.get(f"{PREFIX}/api/projects/{project['id']}/assets/{asset['id']}")
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "video/mp4")
                self.assertNotIn("noncredential-upload-fixture", json.dumps(project))
        self.assertEqual(self.bridge.submit.await_count, 3)


if __name__ == "__main__":
    unittest.main()
