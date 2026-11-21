import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from avatar_studio.preparation_worker import watch_parent

payload = json.loads(sys.stdin.buffer.readline())
threading.Thread(target=watch_parent, daemon=True).start()
assert set(payload["settings"]) <= {"BYTEPLUS_SEED_SPEECH_API_KEY", "BYTEPLUS_REGION"}
assert payload["settings"]["BYTEPLUS_SEED_SPEECH_API_KEY"] == "private-fixture-value"
assert not any("KEY" in name or "TOKEN" in name or "SECRET" in name for name in os.environ)
prompt = payload["graph"]["generate"]["inputs"]["text_prompt"]
if prompt in {"first", "second", "cancel"}:
    root = Path(payload["output"])
    (root / prompt).write_text(str(os.getpid()))
    while not (root / "release").exists():
        time.sleep(0.02)
if prompt == "malformed":
    sys.stdout.write("private-fixture-value")
elif prompt in {"failed", "unknown"}:
    print(json.dumps({"state": prompt, "error": "private-fixture-value"}))
else:
    print(json.dumps({"state": "finished", "outputs": {"audio": [{"filename": "fixture.wav", "type": "output"}]}}))
