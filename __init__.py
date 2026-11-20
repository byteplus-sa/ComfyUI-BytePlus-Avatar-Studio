from pathlib import Path

from comfy_api.latest import ComfyExtension
from server import PromptServer

from .avatar_studio.routes import register
from .avatar_studio.task_record import BytePlusAvatarStudioTaskRecord

WEB_DIRECTORY = "./web"


class BytePlusAvatarStudioExtension(ComfyExtension):
    async def get_node_list(self):
        return [BytePlusAvatarStudioTaskRecord]


async def comfy_entrypoint():
    register(PromptServer.instance, Path(__file__).parent / "studio_dist")
    return BytePlusAvatarStudioExtension()
