import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from avatar_studio.routes import PREFIX, create_routes
from avatar_studio.service import StudioService
from avatar_studio.store import Store


class LoginHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.bridge = Mock()
        self.bridge.login_client_connected.return_value = True
        self.service = StudioService(self.store, self.bridge)
        self.service.generate = AsyncMock(return_value={"accepted": True})
        application = web.Application()
        application.add_routes(create_routes(
            lambda: self.service, lambda request: request.headers.get("Comfy-User", "default"),
            Path(self.temporary.name),
        ))
        self.client = TestClient(TestServer(application))
        await self.client.start_server()
        self.producer = "a" * 64
        self.handoff = "b" * 64
        self.consumer = "c" * 64
        self.consumer_headers = {"X-Studio-Login": self.consumer}
        self.producer_headers = {"X-Studio-Login-Producer": self.producer}
        self.body = {
            "kind": "video", "revision": 0, "operation_id": str(uuid4()), "use_comfy_login": True,
        }
        self.target = f"{PREFIX}/api/projects/{uuid4()}/generate"

    async def asyncTearDown(self):
        await self.client.close()
        await self.service.close()
        self.temporary.cleanup()

    async def auth(self, action, body=None, headers=None):
        return await self.client.post(
            f"{PREFIX}/api/auth/{action}", json=body or {}, headers=headers or self.consumer_headers,
        )

    async def connect(self):
        response = await self.auth("launch", {
            "client_id": "client-1", "handoff": self.handoff,
        }, self.producer_headers)
        self.assertEqual(response.status, 200)
        self.link_id = (await response.json())["link_id"]
        response = await self.auth("claim", {"handoff": self.handoff})
        self.assertEqual(response.status, 200)
        response = await self.auth("state", {"link_id": self.link_id, "connected": True}, self.producer_headers)
        self.assertEqual(response.status, 200)

    async def test_oauth_is_forwarded_only_in_sensitive_video_context(self):
        await self.connect()

        def respond(client_id, data):
            self.service.login_sessions.respond(
                "default", self.producer, self.link_id, data["request_id"], "synthetic-oauth-token", True
            )

        self.bridge.send_login_request.side_effect = respond
        response = await self.client.post(self.target, json=self.body, headers=self.consumer_headers)
        self.assertEqual(response.status, 202)
        self.assertEqual(self.service.generate.call_args.args[-1], {"auth_token_comfy_org": "synthetic-oauth-token"})
        self.assertNotIn("synthetic-oauth-token", await response.text())
        response = await self.auth("status")
        self.assertEqual(await response.json(), {"linked": True, "connected": True})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_login_source_conflicts_and_non_video_requests_are_rejected(self):
        await self.connect()
        for fields, headers in (
            ({"use_saved_upload_key": True}, self.consumer_headers),
            ({}, {**self.consumer_headers, "X-Comfy-Org-Api-Key": "synthetic-key"}),
            ({"kind": "image"}, self.consumer_headers),
            ({"use_comfy_login": "true"}, self.consumer_headers),
        ):
            response = await self.client.post(self.target, json={**self.body, **fields}, headers=headers)
            self.assertEqual(response.status, 400)
        self.service.generate.assert_not_awaited()

    async def test_expired_login_never_creates_an_operation_or_falls_back_to_a_saved_key(self):
        await self.connect()
        self.service.upload_credentials.save("default", "synthetic-saved-key")
        await self.auth("disconnect")
        response = await self.client.post(self.target, json=self.body, headers=self.consumer_headers)
        self.assertEqual(response.status, 401)
        self.service.generate.assert_not_awaited()
        self.assertEqual(self.store.pending_jobs(), [])

    async def test_cross_origin_requests_and_invalid_status_are_rejected(self):
        await self.connect()
        for action in ("launch", "claim", "status", "state", "respond", "disconnect", "sign-in"):
            response = await self.auth(action, headers={
                **self.consumer_headers, "Origin": "https://untrusted.example", "Sec-Fetch-Site": "same-origin",
            })
            self.assertEqual(response.status, 403)
        response = await self.auth("state", {"link_id": self.link_id, "connected": 1}, self.producer_headers)
        self.assertEqual(response.status, 400)

    async def test_other_owners_cannot_claim_or_use_the_login(self):
        await self.connect()
        response = await self.auth("status", headers={**self.consumer_headers, "Comfy-User": "other"})
        self.assertEqual(await response.json(), {"linked": False, "connected": False})
        response = await self.client.post(
            self.target, json=self.body, headers={**self.consumer_headers, "Comfy-User": "other"},
        )
        self.assertEqual(response.status, 401)
        self.service.generate.assert_not_awaited()

    async def test_auth_inputs_and_errors_never_echo_secrets(self):
        response = await self.auth("launch", {"client_id": "client-1", "handoff": self.handoff}, {
            "X-Studio-Login-Producer": "invalid-synthetic-secret",
        })
        self.assertEqual(response.status, 400)
        self.assertNotIn("invalid-synthetic-secret", await response.text())
        response = await self.auth("claim", {"handoff": "x" * 20000})
        self.assertEqual(response.status, 413)
        self.assertNotIn(self.producer, json.dumps(self.store.list("default")))


if __name__ == "__main__":
    unittest.main()
