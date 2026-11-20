from comfy_api.latest import io


class BytePlusAvatarStudioTaskRecord(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="BytePlusAvatarStudioTaskRecord",
            display_name="BytePlus Avatar Studio Task Record",
            category="BytePlus Avatar Studio",
            inputs=[io.String.Input("task_id", default="")],
            outputs=[],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, task_id):
        return io.NodeOutput(ui={"avatar_studio": [{"task_id": task_id}]})
