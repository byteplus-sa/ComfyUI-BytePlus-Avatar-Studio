import io
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np
import av
from PIL import Image

from avatar_studio.media import prepare_audio, prepare_candidate, prepare_reference
from avatar_studio.store import StudioError


def write_audio(path, seconds=4, rate=48000, channels=2, silent=False):
    values = (
        np.zeros(int(seconds * rate), dtype=np.int16)
        if silent
        else (np.sin(np.arange(int(seconds * rate)) * 440 * 2 * np.pi / rate) * 8000).astype(np.int16)
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(np.repeat(values[:, None], channels, axis=1).tobytes())


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reference_is_reencoded_to_metadata_free_rgb_png(self):
        metadata = Image.Exif()
        metadata[274] = 6
        metadata[315] = "Private reference author"
        for format_name in ("JPEG", "PNG", "WEBP"):
            with self.subTest(format=format_name):
                source = io.BytesIO()
                Image.new("RGB", (400, 500), (40, 60, 90)).save(source, format=format_name, exif=metadata)
                path, info = prepare_reference(source.getvalue(), self.root)
                with Image.open(path) as result:
                    self.assertEqual(result.mode, "RGB")
                    self.assertEqual(result.size, (500, 400))
                    self.assertEqual(dict(result.getexif()), {})
                    self.assertNotIn("exif", result.info)
                self.assertEqual(info["mime"], "image/png")

    def test_empty_invalid_small_and_large_references_are_rejected(self):
        for content in (b"", b"not an image", b"x" * (10 * 1024 * 1024 + 1)):
            with self.subTest(size=len(content)), self.assertRaises(StudioError):
                prepare_reference(content, self.root)
        source = io.BytesIO()
        Image.new("RGB", (30, 30)).save(source, format="PNG")
        with self.assertRaises(StudioError):
            prepare_reference(source.getvalue(), self.root)

    def test_audio_is_prepared_before_review_without_duration_changes(self):
        source = self.root / "source.wav"
        write_audio(source)
        path, info = prepare_audio(source, self.root)
        self.assertAlmostEqual(info["duration"], 4, places=3)
        with wave.open(str(path), "rb") as result:
            self.assertEqual(result.getframerate(), 24000)
            self.assertEqual(result.getnchannels(), 1)
            self.assertEqual(result.getsampwidth(), 2)
        self.assertEqual(info["channels"], 1)

    def test_silent_and_invalid_audio_fail_without_leaving_partial_assets(self):
        source = self.root / "source.wav"
        for silent in (True, False):
            if silent:
                write_audio(source, silent=True)
            else:
                source.write_bytes(b"invalid")
            with self.subTest(silent=silent), self.assertRaises(StudioError):
                prepare_audio(source, self.root)
            self.assertEqual(list(self.root.glob("*.wav")), [source])

    def test_five_minute_audio_is_not_truncated_and_stays_under_upload_budget(self):
        source = self.root / "source.wav"
        write_audio(source, seconds=300, rate=24000, channels=1)
        path, info = prepare_audio(source, self.root)
        self.assertEqual(info["duration"], 300)
        self.assertLess(path.stat().st_size, 15 * 1024 * 1024)
        uploaded, metadata = prepare_candidate("audio", source.read_bytes(), self.root)
        self.assertEqual(metadata["duration"], 300)
        self.assertLess(uploaded.stat().st_size, 15 * 1024 * 1024)

    def test_over_five_minutes_fails_instead_of_truncating(self):
        source = self.root / "source.wav"
        write_audio(source, seconds=300.1, rate=24000, channels=1)
        with self.assertRaises(StudioError):
            prepare_audio(source, self.root)
        with self.assertRaises(StudioError):
            prepare_candidate("audio", source.read_bytes(), self.root)

    def test_animated_portraits_are_rejected_without_saved_candidates(self):
        image = io.BytesIO()
        Image.new("RGB", (400, 500), "red").save(
            image,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", (400, 500), "blue")],
            duration=100,
            loop=0,
        )
        with self.assertRaises(StudioError):
            prepare_candidate("image", image.getvalue(), self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_uploaded_portrait_is_a_normalized_candidate(self):
        image = io.BytesIO()
        Image.new("RGB", (400, 500)).save(image, format="JPEG")
        path, metadata = prepare_candidate("image", image.getvalue(), self.root)
        self.assertEqual(metadata["origin"], "upload")
        self.assertEqual(metadata["mime"], "image/png")
        with Image.open(path) as result:
            self.assertEqual(result.size, (400, 500))

    def test_uploaded_audio_is_prepared_for_review_and_short_clips_are_rejected(self):
        source = self.root / "source.wav"
        write_audio(source, seconds=4)
        path, metadata = prepare_candidate("audio", source.read_bytes(), self.root)
        self.assertEqual(metadata["origin"], "upload")
        self.assertEqual(metadata["duration"], 4)
        with wave.open(str(path), "rb") as audio:
            self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getsampwidth()), (1, 24000, 2))
        path.unlink()
        write_audio(source, seconds=3.9)
        with self.assertRaises(StudioError):
            prepare_candidate("audio", source.read_bytes(), self.root)
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_uploads_reject_empty_corrupt_and_playlist_payloads_without_files(self):
        for kind, payload in (
            ("image", b""),
            ("audio", b""),
            ("audio", b"not audio"),
            ("audio", b"#EXTM3U\nhttp://127.0.0.1/private\n"),
            ("audio", b"RIFF\x00\x00\x00\x00WAVEinvalid"),
            ("video", b"anything"),
        ):
            with self.subTest(kind=kind, payload=payload), self.assertRaises(StudioError):
                prepare_candidate(kind, payload, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_mp3_and_flac_uploads_decode_to_reviewable_wav(self):
        samples = (np.sin(np.arange(24000 * 5) * 440 * 2 * np.pi / 24000) * 8000).astype(np.int16)[None, :]
        for format_name, codec in (("mp3", "libmp3lame"), ("flac", "flac")):
            with self.subTest(format=format_name):
                source = self.root / f"source.{format_name}"
                with av.open(str(source), "w", format=format_name) as container:
                    stream = container.add_stream(codec, rate=24000)
                    stream.layout = "mono"
                    frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
                    frame.sample_rate = 24000
                    for packet in stream.encode(frame):
                        container.mux(packet)
                    for packet in stream.encode():
                        container.mux(packet)
                path, metadata = prepare_candidate("audio", source.read_bytes(), self.root)
                self.assertTrue(4.9 <= metadata["duration"] <= 5.1)
                with wave.open(str(path), "rb") as output:
                    self.assertEqual(output.getframerate(), 24000)


if __name__ == "__main__":
    unittest.main()
