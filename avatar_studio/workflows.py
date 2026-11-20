import hashlib

from .store import StudioError

PORTRAIT_SIZES = {"1:1": (1024, 1024), "3:4": (864, 1152), "9:16": (768, 1366)}


def audio_prompt(project):
    script = project["script"]
    if not script.strip():
        raise StudioError("Add a narration script first.")
    prompt = (
        f"{project['voice_direction']}\nLanguage: {project['language']}.\n"
        "One speaker. Clean speech, no music or sound effects. Speak these exact lines:\n"
        f"{script}"
    )
    if len(prompt) > 3000:
        raise StudioError("The script and voice direction together exceed Seed Audio's 3000-character prompt limit.")
    return prompt


def build_workflow(project, job, sources):
    node = f"avatar_{job['id']}"
    prefix = f"byteplus_avatar_studio/{job.get('project_id', 'test')}/{job['id']}"
    seed = int.from_bytes(hashlib.sha256(job["id"].encode()).digest()[:4], "big") & (2**31 - 1)
    graph = {}
    if job["kind"] == "image":
        if not project["character_prompt"].strip():
            raise StudioError("Describe the character first.")
        width, height = PORTRAIT_SIZES[project["ratio"]]
        inputs = {
            "prompt": project["character_prompt"],
            "model": "seedream 5.5",
            "model.size_preset": "Custom",
            "model.width": width,
            "model.height": height,
            "model.seed": seed,
            "model.watermark": project["enable_watermark"],
            "model.generation_count": 1,
            "model.output_format": "png",
            "model.background": "opaque",
            "model.prompt_optimization": "standard",
        }
        if sources.get("reference"):
            graph["reference"] = {"class_type": "LoadImage", "inputs": {"image": sources["reference"]}}
            inputs["model.images.image_1"] = ["reference", 0]
        graph[node] = {"class_type": "BytePlusSeedream", "inputs": inputs}
        graph["save"] = {"class_type": "SaveImage", "inputs": {"images": [node, 0], "filename_prefix": prefix}}
        return graph
    if job["kind"] == "audio":
        graph[node] = {
            "class_type": "BytePlusSeedAudio",
            "inputs": {
                "text_prompt": audio_prompt(project),
                "reference_mode": "text only",
                "sample_rate": "24000",
                "speech_rate": 0,
                "loudness_rate": 0,
                "pitch_rate": 0,
                "seed": seed,
                "model": "seed-audio-1.0",
                "audio_format": "wav",
                "generation_count": 1,
            },
        }
        graph["save"] = {"class_type": "SaveAudio", "inputs": {"audio": [node, 0], "filename_prefix": prefix}}
        return graph
    if job["kind"] != "video":
        raise StudioError("Unknown generation stage.")
    if job.get("recovering"):
        graph[node] = {
            "class_type": "BytePlusOmniHumanTaskResult",
            "inputs": {"task_id": job["task_id"], "wait_for_completion": True},
        }
    else:
        if not sources.get("image") or not sources.get("audio"):
            raise StudioError("Both reviewed sources are required.")
        graph["portrait"] = {"class_type": "LoadImage", "inputs": {"image": sources["image"]}}
        graph["narration"] = {"class_type": "LoadAudio", "inputs": {"audio": sources["audio"]}}
        graph[node] = {
            "class_type": "BytePlusOmniHuman",
            "inputs": {
                "image": ["portrait", 0],
                "audio": ["narration", 0],
                "prompt": project["motion_prompt"],
                "enable_watermark": project["enable_watermark"],
                "seed": seed,
            },
        }
    graph["record"] = {
        "class_type": "BytePlusAvatarStudioTaskRecord",
        "inputs": {"task_id": [node, 1]},
    }
    graph["save"] = {
        "class_type": "SaveVideo",
        "inputs": {"video": [node, 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"},
    }
    return graph
