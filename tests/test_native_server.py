import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("native_server", Path(__file__).with_name("native_server.py"))
native_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_server)


class NativeServerTests(unittest.TestCase):
    def test_offline_flag_is_used_only_when_supported_by_the_target_core(self):
        for help_text in ("usage: main.py [--cpu]", "usage: main.py [--cpu] [--offline]"):
            with self.subTest(help_text=help_text), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("main.py", "__init__.py", "studio_dist/index.html"):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                process = Mock()
                process.wait.return_value = 0
                process.poll.return_value = 0
                with (
                    patch.object(native_server.subprocess, "run", return_value=Mock(stdout=help_text)),
                    patch.object(native_server.subprocess, "Popen", return_value=process) as launch,
                    patch.dict(native_server.os.environ, {"BYTEPLUS_CV_API_KEY": "synthetic-key"}),
                ):
                    self.assertEqual(native_server.run(root, root, root, 8209), 0)
                command = launch.call_args.args[0]
                self.assertEqual("--offline" in command, "--offline" in help_text)
                self.assertIn("--database-url", command)
                self.assertIn("--disable-all-custom-nodes", command)
                environment = launch.call_args.kwargs["env"]
                self.assertNotIn("BYTEPLUS_CV_API_KEY", environment)
                self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
