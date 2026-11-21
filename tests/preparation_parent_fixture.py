import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avatar_studio.preparation_process import PreparationProcess

root = Path(sys.argv[1])
tempfile.tempdir = str(root)
runner = PreparationProcess(
    root,
    root,
    root,
    root,
    lambda name: "private-fixture-value" if name == "BYTEPLUS_SEED_SPEECH_API_KEY" else "",
)
runner.script = Path(__file__).with_name("preparation_worker_fixture.py")
asyncio.run(
    runner.run(
        {
            "generate": {"class_type": "BytePlusSeedAudio", "inputs": {"text_prompt": "cancel"}},
            "save": {"class_type": "SaveAudio", "inputs": {}},
        }
    )
)
