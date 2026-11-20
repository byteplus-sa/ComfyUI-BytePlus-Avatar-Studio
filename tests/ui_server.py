import argparse
import sys
import tempfile
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avatar_studio.routes import create_routes
from avatar_studio.service import StudioService
from avatar_studio.store import Store, StudioError


class OfflineBridge:
    def setup(self):
        return {
            "ready": True,
            "missing_nodes": [],
            "version": "0.10.0",
            "credentials": {"image": False, "audio": False, "video": False},
            "test_mode": True,
        }

    def stage_ready(self, *args, **kwargs):
        raise StudioError("Offline preview: provider generation is disabled.", 503)


def application(dist):
    temporary = tempfile.TemporaryDirectory(prefix="avatar-ui-preview-")
    store = Store(temporary.name)
    service = StudioService(store, OfflineBridge())
    app = web.Application()
    app.add_routes(create_routes(lambda: service, lambda request: "default", dist))

    async def cleanup(app):
        await service.close()
        temporary.cleanup()

    app.on_cleanup.append(cleanup)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Disposable Studio UI server. Cannot submit provider work.")
    parser.add_argument("--port", type=int, default=8207)
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[1] / "studio_dist")
    arguments = parser.parse_args()
    web.run_app(application(arguments.dist), host="127.0.0.1", port=arguments.port, access_log=None)
