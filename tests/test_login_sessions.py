import asyncio
import unittest
from unittest.mock import Mock

from avatar_studio.login_sessions import LoginSessions
from avatar_studio.store import StudioError


class LoginSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.bridge = Mock()
        self.bridge.login_client_connected.return_value = True
        self.sessions = LoginSessions(self.bridge, clock=lambda: self.now)
        self.producer = "a" * 64
        self.handoff = "b" * 64
        self.consumer = "c" * 64
        self.link = self.sessions.launch("owner", "client-1", self.producer, self.handoff)["link_id"]

    def tearDown(self):
        self.sessions.close()

    def claim(self):
        return self.sessions.claim("owner", self.handoff, self.consumer)

    def connect(self):
        self.claim()
        self.sessions.update("owner", self.producer, self.link, True)

    def respond(self, token="fixture-access-token", connected=True):
        client, data = self.bridge.send_login_request.call_args.args
        self.assertEqual(client, "client-1")
        return self.sessions.respond(
            "owner", self.producer, self.link, data["request_id"], token, connected
        )

    async def test_handoff_is_single_use_and_status_contains_no_capabilities(self):
        self.assertEqual(self.claim(), {"linked": True, "connected": False})
        with self.assertRaises(StudioError):
            self.sessions.claim("owner", self.handoff, "d" * 64)
        self.assertEqual(self.claim(), {"linked": True, "connected": False})
        self.sessions.update("owner", self.producer, self.link, True)
        self.assertEqual(self.sessions.status("owner", self.consumer), {"linked": True, "connected": True})

    async def test_owner_and_producer_cannot_access_another_link(self):
        with self.assertRaises(StudioError):
            self.sessions.claim("other", self.handoff, self.consumer)
        self.claim()
        for owner, producer in (("other", self.producer), ("owner", "e" * 64)):
            with self.assertRaises(StudioError):
                self.sessions.update(owner, producer, self.link, True)
        self.assertEqual(self.sessions.status("other", self.consumer), {"linked": False, "connected": False})

    async def test_token_is_requested_fresh_and_not_returned_in_status(self):
        self.connect()
        for token in ("first-access-token", "refreshed-access-token"):
            request = asyncio.create_task(self.sessions.token("owner", self.consumer))
            await asyncio.sleep(0)
            self.respond(token)
            self.assertEqual(await request, token)
            self.assertEqual(self.sessions.status("owner", self.consumer), {"linked": True, "connected": True})
            self.assertEqual(self.sessions.pending, {})
        self.assertEqual(self.bridge.send_login_request.call_count, 2)

    async def test_bad_producer_and_stale_responses_cannot_complete_a_request(self):
        self.connect()
        request = asyncio.create_task(self.sessions.token("owner", self.consumer))
        await asyncio.sleep(0)
        data = self.bridge.send_login_request.call_args.args[1]
        for producer, request_id in (("e" * 64, data["request_id"]), (self.producer, "f" * 64)):
            with self.assertRaises(StudioError):
                self.sessions.respond("owner", producer, self.link, request_id, "untrusted-token", True)
            self.assertFalse(request.done())
        self.respond()
        self.assertEqual(await request, "fixture-access-token")

    async def test_sign_in_can_start_signed_out_without_returning_a_token(self):
        self.claim()
        request = asyncio.create_task(self.sessions.sign_in("owner", self.consumer))
        await asyncio.sleep(0)
        self.assertEqual(self.bridge.send_login_request.call_args.args[1]["action"], "sign_in")
        self.respond(token=None)
        self.assertEqual(await request, {"linked": True, "connected": True})

    async def test_logout_and_disconnection_fail_before_using_credentials(self):
        self.connect()
        request = asyncio.create_task(self.sessions.token("owner", self.consumer))
        await asyncio.sleep(0)
        self.sessions.update("owner", self.producer, self.link, False)
        with self.assertRaises(StudioError):
            await request
        with self.assertRaises(StudioError):
            await self.sessions.token("owner", self.consumer)
        self.sessions.update("owner", self.producer, self.link, True)
        self.bridge.login_client_connected.return_value = False
        self.assertEqual(self.sessions.status("owner", self.consumer), {"linked": False, "connected": False})
        with self.assertRaises(StudioError):
            await self.sessions.token("owner", self.consumer)

    async def test_expired_handoffs_and_sessions_are_not_reusable(self):
        self.now += 61
        with self.assertRaises(StudioError):
            self.claim()
        self.link = self.sessions.launch("owner", "client-1", self.producer, self.handoff)["link_id"]
        self.connect()
        self.now += 8 * 3600 + 1
        self.assertEqual(self.sessions.status("owner", self.consumer), {"linked": False, "connected": False})

    async def test_duplicate_capabilities_and_capacity_are_rejected(self):
        with self.assertRaises(StudioError):
            self.sessions.launch("owner", "client-1", "d" * 64, self.handoff)
        self.sessions.maximum = 1
        with self.assertRaises(StudioError):
            self.sessions.launch("owner", "client-1", "d" * 64, "e" * 64)

    async def test_concurrent_requests_and_timeouts_fail_closed(self):
        self.connect()
        self.sessions.token_timeout = 0.01
        request = asyncio.create_task(self.sessions.token("owner", self.consumer))
        await asyncio.sleep(0)
        with self.assertRaises(StudioError):
            await self.sessions.token("owner", self.consumer)
        with self.assertRaises(StudioError):
            await request
        self.assertEqual(self.sessions.pending, {})

    async def test_canceled_requests_and_removed_links_cannot_accept_delayed_tokens(self):
        self.connect()
        request = asyncio.create_task(self.sessions.token("owner", self.consumer))
        await asyncio.sleep(0)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        with self.assertRaises(StudioError):
            self.respond()
        self.sessions.disconnect("owner", self.consumer)
        self.assertEqual(self.sessions.status("owner", self.consumer), {"linked": False, "connected": False})

    async def test_invalid_tokens_are_rejected_without_echoing_them(self):
        self.connect()
        for token in ("", "Bearer fixture", "fixture\nsecret", "x" * 8193, None):
            request = asyncio.create_task(self.sessions.token("owner", self.consumer))
            await asyncio.sleep(0)
            self.respond(token)
            with self.assertRaises(StudioError) as error:
                await request
            self.assertNotIn("secret", str(error.exception))

    async def test_invalid_capabilities_and_flags_are_rejected(self):
        for secret in ("", "x", None, "G" * 64):
            with self.assertRaises(StudioError):
                self.sessions.claim("owner", secret, self.consumer)
        with self.assertRaises(StudioError):
            self.sessions.update("owner", self.producer, self.link, "true")

    async def test_independent_tabs_cannot_exchange_consumers(self):
        self.connect()
        other = self.sessions.launch("owner", "client-2", "d" * 64, "e" * 64)["link_id"]
        self.sessions.claim("owner", "e" * 64, "f" * 64)
        self.sessions.update("owner", "d" * 64, other, True)
        self.sessions.disconnect("owner", self.consumer)
        self.assertEqual(self.sessions.status("owner", "f" * 64), {"linked": True, "connected": True})


if __name__ == "__main__":
    unittest.main()
