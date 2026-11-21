import asyncio
import importlib
import inspect
from typing import Any

from .store import StudioError


def preparation_kind(graph):
    types = [node["class_type"] for node in graph.values()]
    if not ({"BytePlusSeedream", "BytePlusSeedAudio"} & set(types)):
        return None
    if types in (["BytePlusSeedream", "SaveImage"], ["LoadImage", "BytePlusSeedream", "SaveImage"]):
        return "image"
    if types == ["BytePlusSeedAudio", "SaveAudio"]:
        return "audio"
    raise StudioError("Only Studio portrait and narration workflows can use parallel preparation.", 422)


def validate_preparation(nodes, graph):
    kind = preparation_kind(graph)
    if not kind:
        raise StudioError("This workflow is not a preparation workflow.", 422)
    if kind == "audio":
        module = importlib.import_module(nodes.NODE_CLASS_MAPPINGS["BytePlusSeedAudio"].__module__)
        inputs = next(node["inputs"] for node in graph.values() if node["class_type"] == "BytePlusSeedAudio")
        try:
            module.validate_seed_audio_inputs(inputs["text_prompt"], inputs["reference_mode"], [], False)
        except Exception:
            raise StudioError(
                "Narration is invalid for Seed Audio text-only mode. Remove audio-reference tags and check its length.",
                422,
            ) from None


class PreparationRunner:
    def __init__(self, nodes, execution):
        self.nodes = nodes
        self.execution = execution

    async def run(self, graph):
        if not preparation_kind(graph):
            raise StudioError("This workflow is not a preparation workflow.", 422)
        outputs: dict[str, list[Any]] = {}
        saved = {}
        for node_id, node in graph.items():
            inputs = {
                name: outputs[value[0]][value[1]] if isinstance(value, list) else value
                for name, value in node["inputs"].items()
            }
            node_class = self.nodes.NODE_CLASS_MAPPINGS[node["class_type"]]
            values, ui = await self.invoke(node_class, inputs, graph)
            outputs[node_id] = values
            if node_id == "save":
                saved = ui
        if not (saved.get("images") or saved.get("audio")):
            raise StudioError("Preparation did not return a saved candidate.")
        return saved

    async def invoke(self, node_class, inputs, graph):
        from comfy_api.internal import make_locked_method_func
        from comfy_api.latest import _io, io
        from comfy_execution.graph_utils import ExecutionBlocker

        input_lists, missing, context = self.execution.get_input_data(inputs, node_class, None)
        if missing:
            raise StudioError("Preparation has an unresolved input.", 422)
        values = {name: items[0] for name, items in input_lists.items()}
        if issubclass(node_class, io.ComfyNode):
            if io.Hidden.prompt in context["hidden_inputs"]:
                context["hidden_inputs"][io.Hidden.prompt] = graph
            node_class.VALIDATE_CLASS()
            clone = node_class.PREPARE_CLASS_CLONE(context)
            function = make_locked_method_func(node_class, node_class.FUNCTION, clone)
            values = _io.build_nested_inputs(values, context)
        else:
            if "prompt" in values:
                values["prompt"] = graph
            function = getattr(node_class(), node_class.FUNCTION)
        if inspect.iscoroutinefunction(function):
            result = await function(**values)
        else:
            worker = asyncio.create_task(asyncio.to_thread(function, **values))
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise
        if isinstance(result, dict):
            returned, ui = result.get("result", ()), result.get("ui", {})
        else:
            if getattr(result, "block_execution", None) is not None:
                raise StudioError("The preparation node could not produce a candidate.")
            returned, ui = getattr(result, "result", result), getattr(result, "ui", None) or {}
        outputs = []
        list_outputs = getattr(node_class, "OUTPUT_IS_LIST", ())
        for index, value in enumerate(returned or ()):
            if index < len(list_outputs) and list_outputs[index]:
                if not isinstance(value, list) or len(value) != 1:
                    raise StudioError("Preparation must return exactly one candidate.")
                value = value[0]
            if isinstance(value, ExecutionBlocker):
                raise StudioError("The preparation node could not produce a candidate.")
            outputs.append(value)
        return outputs, ui if isinstance(ui, dict) else ui.as_dict()
