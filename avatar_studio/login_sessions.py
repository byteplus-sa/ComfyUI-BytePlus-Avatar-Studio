import asyncio
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4

from .store import StudioError


def capability(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise StudioError("Invalid Studio login link.", 400)
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def valid_token(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 8192
        and all(33 <= ord(character) <= 126 for character in value)
    )


@dataclass
class LoginLink:
    owner: str
    client_id: str
    producer: str
    handoff: str
    expires: float
    consumer: str | None = None
    connected: bool = False


class LoginSessions:
    def __init__(self, bridge, clock=time.monotonic):
        self.bridge = bridge
        self.clock = clock
        self.links: dict[str, LoginLink] = {}
        self.pending: dict[str, tuple[str, str, asyncio.Future]] = {}
        self.maximum = 64
        self.token_timeout = 15
        self.sign_in_timeout = 180

    def _reject_pending(self, link_id):
        pending = self.pending.pop(link_id, None)
        if pending and not pending[2].done():
            pending[2].set_exception(StudioError("ComfyUI login disconnected. Reopen Studio from ComfyUI.", 401))

    def _remove(self, link_id):
        self.links.pop(link_id, None)
        self._reject_pending(link_id)

    def _prune(self):
        for link_id, link in list(self.links.items()):
            if link.expires <= self.clock() or not self.bridge.login_client_connected(link.client_id):
                self._remove(link_id)

    def launch(self, owner, client_id, producer, handoff):
        if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_id):
            raise StudioError("The ComfyUI connection is unavailable.", 409)
        producer_key, handoff_key = capability(producer), capability(handoff)
        self._prune()
        if not self.bridge.login_client_connected(client_id):
            raise StudioError("The ComfyUI connection is unavailable.", 409)
        if len(self.links) >= self.maximum:
            raise StudioError("Too many Studio login links. Close an existing session first.", 429)
        if any(link.producer == producer_key or link.handoff == handoff_key for link in self.links.values()):
            raise StudioError("This login link has already been registered.", 409)
        link_id = str(uuid4())
        self.links[link_id] = LoginLink(owner, client_id, producer_key, handoff_key, self.clock() + 60)
        return {"link_id": link_id}

    def claim(self, owner, handoff, consumer):
        handoff_key, consumer_key = capability(handoff), capability(consumer)
        self._prune()
        for link in self.links.values():
            if link.owner == owner and link.handoff == handoff_key:
                if link.consumer and link.consumer != consumer_key:
                    raise StudioError("This login link has already been used. Reopen Studio from ComfyUI.", 409)
                if any(other is not link and other.consumer == consumer_key for other in self.links.values()):
                    raise StudioError("This Studio tab already has a login link.", 409)
                if link.consumer is None:
                    link.consumer = consumer_key
                    link.expires = self.clock() + 8 * 3600
                return {"linked": True, "connected": link.connected}
        raise StudioError("The login link is unavailable. Reopen Studio from ComfyUI.", 404)

    def _producer(self, owner, producer, link_id):
        producer_key = capability(producer)
        self._prune()
        link = self.links.get(link_id)
        if not link or link.owner != owner or link.producer != producer_key:
            raise StudioError("The login link is unavailable.", 404)
        return link

    def _consumer(self, owner, consumer):
        consumer_key = capability(consumer)
        self._prune()
        return next(
            ((link_id, link) for link_id, link in self.links.items()
             if link.owner == owner and link.consumer == consumer_key),
            (None, None),
        )

    def status(self, owner, consumer):
        _, link = self._consumer(owner, consumer)
        return {"linked": link is not None, "connected": bool(link and link.connected)}

    def update(self, owner, producer, link_id, connected):
        if type(connected) is not bool:
            raise StudioError("Invalid login status.")
        link = self._producer(owner, producer, link_id)
        link.connected = connected
        if not connected:
            pending = self.pending.get(link_id)
            if pending and pending[1] == "token":
                self._reject_pending(link_id)
        return {"connected": connected}

    def disconnect(self, owner, consumer):
        link_id, _ = self._consumer(owner, consumer)
        if link_id:
            self._remove(link_id)
        return {"linked": False, "connected": False}

    def disconnect_producer(self, owner, producer, link_id):
        self._producer(owner, producer, link_id)
        self._remove(link_id)
        return {"connected": False}

    async def _request(self, owner, consumer, action):
        link_id, link = self._consumer(owner, consumer)
        if not link or (action == "token" and not link.connected):
            raise StudioError("Connect your ComfyUI login before generating video.", 401)
        if link_id in self.pending:
            raise StudioError("A ComfyUI login request is already pending.", 409)
        request_id = secrets.token_hex(32)
        future = asyncio.get_running_loop().create_future()
        self.pending[link_id] = (request_id, action, future)
        try:
            self.bridge.send_login_request(
                link.client_id, {"link_id": link_id, "request_id": request_id, "action": action}
            )
            timeout = self.token_timeout if action == "token" else self.sign_in_timeout
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise StudioError("ComfyUI login did not respond. Return to ComfyUI and reconnect.", 401) from None
        finally:
            if self.pending.get(link_id, (None,))[0] == request_id:
                self.pending.pop(link_id, None)
            if not future.done():
                future.cancel()

    async def token(self, owner, consumer):
        return await self._request(owner, consumer, "token")

    async def sign_in(self, owner, consumer):
        await self._request(owner, consumer, "sign_in")
        return self.status(owner, consumer)

    def respond(self, owner, producer, link_id, request_id, token, connected):
        link = self._producer(owner, producer, link_id)
        capability(request_id)
        if type(connected) is not bool:
            raise StudioError("Invalid login status.")
        pending = self.pending.get(link_id)
        if not pending or pending[0] != request_id or pending[2].done():
            raise StudioError("This login request is no longer pending.", 409)
        _, action, future = pending
        link.connected = connected
        if not connected or (action == "token" and not valid_token(token)):
            future.set_exception(StudioError("ComfyUI login could not authorize this upload. Reconnect first.", 401))
        else:
            future.set_result(token if action == "token" else True)
        return {"connected": connected}

    def close(self):
        for link_id in list(self.links):
            self._remove(link_id)
