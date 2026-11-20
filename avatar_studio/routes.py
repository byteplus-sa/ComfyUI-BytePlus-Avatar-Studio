import asyncio
import json
import logging
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .media import MAX_AUDIO_UPLOAD_BYTES, MAX_REFERENCE_BYTES
from .store import StudioError
from .upload_credentials import validate_upload_key

PREFIX = "/byteplus/avatar-studio"
logger = logging.getLogger("BytePlusAvatarStudio")


def check_origin(request):
    site = request.headers.get("Sec-Fetch-Site")
    if site and site not in {"same-origin", "none"}:
        raise StudioError("Cross-origin requests are not allowed.", 403)
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        raise StudioError("Cross-origin requests are not allowed.", 403)


def guard(handler):
    @wraps(handler)
    async def wrapped(request):
        try:
            if request.method not in {"GET", "HEAD"}:
                check_origin(request)
            response = await handler(request)
        except StudioError as error:
            response = web.json_response({"error": str(error)}, status=error.status)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, KeyError):
            response = web.json_response({"error": "Invalid request."}, status=400)
        except Exception:
            logger.warning("Avatar Studio request failed; sensitive exception details were withheld.")
            response = web.json_response(
                {"error": "A local Studio operation failed. Check ComfyUI and keep any task ID."}, status=500
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    return wrapped


async def bounded_body(request, maximum):
    if request.content_length is not None and request.content_length > maximum:
        raise StudioError("Request body is too large.", 413)
    data = bytearray()
    async for chunk in request.content.iter_chunked(64 * 1024):
        data.extend(chunk)
        if len(data) > maximum:
            raise StudioError("Request body is too large.", 413)
    return bytes(data)


async def payload(request):
    body = json.loads(await bounded_body(request, 16 * 1024))
    if not isinstance(body, dict):
        raise StudioError("A JSON object is required.")
    return body


def create_routes(service_provider, owner_provider, dist):
    routes = web.RouteTableDef()
    dist = Path(dist).resolve()

    @routes.get(f"{PREFIX}/api/setup")
    @guard
    async def setup(request):
        owner_provider(request)
        return web.json_response(service_provider().bridge.setup())

    @routes.post(f"{PREFIX}/api/auth/{{action}}")
    @guard
    async def login(request):
        owner = owner_provider(request)
        sessions = service_provider().login_sessions
        data = await payload(request)
        action = request.match_info["action"]
        producer = request.headers.get("X-Studio-Login-Producer", "")
        consumer = request.headers.get("X-Studio-Login", "")
        if producer and consumer:
            raise StudioError("Select one login-link role.")
        if action == "launch":
            result = sessions.launch(owner, data["client_id"], producer, data["handoff"])
        elif action == "claim":
            result = sessions.claim(owner, data["handoff"], consumer)
        elif action == "status":
            result = sessions.status(owner, consumer)
        elif action == "state":
            result = sessions.update(owner, producer, data["link_id"], data["connected"])
        elif action == "respond":
            result = sessions.respond(
                owner, producer, data["link_id"], data["request_id"], data.get("token"), data["connected"]
            )
        elif action == "sign-in":
            result = await sessions.sign_in(owner, consumer)
        elif action == "disconnect":
            result = (
                sessions.disconnect_producer(owner, producer, data["link_id"])
                if producer else sessions.disconnect(owner, consumer)
            )
        else:
            raise StudioError("Login action not found.", 404)
        return web.json_response(result)

    @routes.get(f"{PREFIX}/api/settings/upload-key")
    @guard
    async def upload_key_status(request):
        check_origin(request)
        owner = owner_provider(request)
        status = await asyncio.to_thread(service_provider().upload_credentials.status, owner)
        return web.json_response(status)

    @routes.post(f"{PREFIX}/api/settings/upload-key")
    @guard
    async def save_upload_key(request):
        owner = owner_provider(request)
        data = await payload(request)
        if set(data) != {"value", "remember"} or data.get("remember") is not True:
            raise StudioError("Explicit permission to remember the upload key is required.")
        await asyncio.to_thread(service_provider().upload_credentials.save, owner, data["value"])
        return web.json_response({"configured": True})

    @routes.delete(f"{PREFIX}/api/settings/upload-key")
    @guard
    async def remove_upload_key(request):
        owner = owner_provider(request)
        await asyncio.to_thread(service_provider().upload_credentials.remove, owner)
        return web.json_response({"configured": False})

    @routes.get(f"{PREFIX}/api/projects")
    @guard
    async def projects(request):
        return web.json_response({"projects": service_provider().store.list(owner_provider(request))})

    @routes.post(f"{PREFIX}/api/projects")
    @guard
    async def create(request):
        data = await payload(request)
        return web.json_response(
            service_provider().store.create(owner_provider(request), data.get("title", "Untitled avatar")), status=201
        )

    @routes.get(f"{PREFIX}/api/projects/{{project_id}}")
    @guard
    async def project(request):
        return web.json_response(
            service_provider().store.get(owner_provider(request), request.match_info["project_id"])
        )

    @routes.patch(f"{PREFIX}/api/projects/{{project_id}}")
    @guard
    async def update(request):
        data = await payload(request)
        return web.json_response(
            service_provider().store.update(
                owner_provider(request), request.match_info["project_id"], data["revision"], data["fields"]
            )
        )

    @routes.post(f"{PREFIX}/api/projects/{{project_id}}/reference")
    @guard
    async def reference(request):
        try:
            revision = int(request.headers.get("X-Project-Revision", ""))
        except ValueError:
            raise StudioError("A project revision is required.") from None
        owner = owner_provider(request)
        project_id = request.match_info["project_id"]
        service = service_provider()
        service.store.get(owner, project_id)
        data = await bounded_body(request, MAX_REFERENCE_BYTES)
        return web.json_response(await service.reference(owner, project_id, revision, data))

    @routes.delete(f"{PREFIX}/api/projects/{{project_id}}/reference")
    @guard
    async def remove_reference(request):
        data = await payload(request)
        return web.json_response(
            service_provider().store.remove_reference(
                owner_provider(request), request.match_info["project_id"], data["revision"]
            )
        )

    @routes.post(f"{PREFIX}/api/projects/{{project_id}}/candidates/{{kind}}")
    @guard
    async def upload_candidate(request):
        kind = request.match_info["kind"]
        if kind not in {"image", "audio"}:
            raise StudioError("Only portraits and narration can be uploaded.")
        try:
            revision = int(request.headers.get("X-Project-Revision", ""))
        except ValueError:
            raise StudioError("A project revision is required.") from None
        owner = owner_provider(request)
        project_id = request.match_info["project_id"]
        service = service_provider()
        service.store.get(owner, project_id)
        data = await bounded_body(request, MAX_REFERENCE_BYTES if kind == "image" else MAX_AUDIO_UPLOAD_BYTES)
        return web.json_response(await service.upload_candidate(owner, project_id, revision, kind, data))

    @routes.post(f"{PREFIX}/api/projects/{{project_id}}/approve")
    @guard
    async def approve(request):
        data = await payload(request)
        return web.json_response(
            service_provider().store.approve(
                owner_provider(request),
                request.match_info["project_id"],
                data["revision"],
                data["kind"],
                data["asset_id"],
                data["sha256"],
            )
        )

    @routes.post(f"{PREFIX}/api/projects/{{project_id}}/generate")
    @guard
    async def generate(request):
        data = await payload(request)
        owner = owner_provider(request)
        service = service_provider()
        use_saved = data.get("use_saved_upload_key", False)
        use_login = data.get("use_comfy_login", False)
        if type(use_saved) is not bool or type(use_login) is not bool:
            raise StudioError("Invalid upload authentication selection.")
        supplied = request.headers.get("X-Comfy-Org-Api-Key", "")
        if (
            sum((use_saved, use_login, bool(supplied))) > 1
            or ((use_saved or use_login) and data["kind"] != "video")
        ):
            raise StudioError("Select exactly one upload authentication source for video generation.")
        key = ""
        sensitive = {}
        if data["kind"] == "video":
            if use_login:
                sensitive["auth_token_comfy_org"] = await service.login_sessions.token(
                    owner, request.headers.get("X-Studio-Login", "")
                )
            elif use_saved:
                key = await asyncio.to_thread(service.upload_credentials.read, owner)
                if not key:
                    raise StudioError("The saved upload key is no longer available. Set it again in Settings.", 409)
            elif supplied:
                key = validate_upload_key(supplied)
        if key:
            sensitive["api_key_comfy_org"] = key
        return web.json_response(
            await service.generate(
                owner,
                request.match_info["project_id"],
                data["revision"],
                data["kind"],
                data["operation_id"],
                sensitive,
            ),
            status=202,
        )

    @routes.post(f"{PREFIX}/api/jobs/{{job_id}}/recover")
    @guard
    async def recover(request):
        data = await payload(request)
        return web.json_response(
            await service_provider().recover(owner_provider(request), request.match_info["job_id"], data["task_id"])
        )

    @routes.post(f"{PREFIX}/api/jobs/{{job_id}}/cancel")
    @guard
    async def cancel(request):
        return web.json_response(await service_provider().cancel(owner_provider(request), request.match_info["job_id"]))

    @routes.get(f"{PREFIX}/api/projects/{{project_id}}/assets/{{asset_id}}")
    @guard
    async def asset(request):
        service = service_provider()
        selected = service.store.asset(
            owner_provider(request), request.match_info["project_id"], request.match_info["asset_id"]
        )
        return web.FileResponse(service.store.asset_path(selected), headers={"Content-Type": selected["mime"]})

    @routes.get(PREFIX)
    async def redirect(request):
        raise web.HTTPFound(f"{PREFIX}/")

    @routes.get(f"{PREFIX}/")
    @guard
    async def index(request):
        owner_provider(request)
        if not (dist / "index.html").is_file():
            raise StudioError(
                "The bundled Studio frontend is missing. Install a complete distribution or build frontend assets.", 503
            )
        return web.FileResponse(dist / "index.html")

    @routes.get(f"{PREFIX}/assets/{{filename}}")
    @guard
    async def bundle(request):
        name = request.match_info["filename"]
        path = (dist / "assets" / name).resolve()
        if (
            not path.is_relative_to(dist / "assets")
            or path.suffix not in {".js", ".css", ".woff2"}
            or not path.is_file()
        ):
            raise StudioError("Asset not found.", 404)
        return web.FileResponse(path)

    return routes


def register(server, dist):
    import folder_paths

    from .bridge import ComfyBridge
    from .service import StudioService
    from .store import Store

    holder = {}

    def service_provider():
        if "service" not in holder:
            store = Store(Path(folder_paths.get_user_directory()) / "byteplus_avatar_studio")
            holder["service"] = StudioService(store, ComfyBridge(server))
            holder["service"].start()
        return holder["service"]

    def owner_provider(request):
        owner = server.user_manager.get_request_user_id(request)
        if not owner:
            raise StudioError("A ComfyUI user is required.", 401)
        return owner

    async def cleanup(app):
        if "service" in holder:
            await holder["service"].close()

    for route in create_routes(service_provider, owner_provider, dist):
        server.routes.route(route.method, route.path, **route.kwargs)(route.handler)
    server.app.on_cleanup.append(cleanup)
