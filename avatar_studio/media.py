import io
import shutil
import wave
from pathlib import Path
from uuid import uuid4

import av
from PIL import Image, ImageOps

from .store import StudioError

MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 750 * 1024 * 1024


def prepare_image(source, media_dir):
    destination = Path(media_dir) / f"{uuid4()}.png"
    try:
        with Image.open(source, formats=("PNG", "JPEG", "WEBP")) as opened:
            if opened.width * opened.height > 24_000_000 or max(opened.size) > 6000:
                raise StudioError("The image is too large. Use at most 6000 pixels per side and 24 megapixels.")
            if min(opened.size) < 300 or not 0.4 <= opened.width / opened.height <= 2.5:
                raise StudioError("Use an image at least 300 pixels per side with a supported portrait ratio.")
            if getattr(opened, "n_frames", 1) != 1:
                raise StudioError("Use a still character image, not an animation.")
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.save(destination, format="PNG")
            return destination, {"mime": "image/png", "width": image.width, "height": image.height}
    except StudioError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        destination.unlink(missing_ok=True)
        raise StudioError("The image could not be decoded. Use a valid PNG, JPEG or WebP.") from None


def prepare_reference(data, media_dir):
    if not data or len(data) > MAX_REFERENCE_BYTES:
        raise StudioError("The reference picture must be nonempty and at most 10 MB.", 413)
    return prepare_image(io.BytesIO(data), media_dir)


def prepare_audio(source, media_dir, format_name=None):
    destination = Path(media_dir) / f"{uuid4()}.wav"
    samples = 0
    peak = 0
    try:
        input_source = source if hasattr(source, "read") else str(source)
        options = {"protocol_whitelist": ""} if format_name else {}
        with (
            av.open(input_source, format=format_name, options=options) as container,
            wave.open(str(destination), "wb") as output,
        ):
            if not container.streams.audio:
                raise StudioError("No audio stream was found.")
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    values = converted.to_ndarray()
                    samples += converted.samples
                    if samples > 300 * 24000:
                        raise StudioError("The narration exceeds OmniHuman's 300-second limit. Use a shorter clip.")
                    peak = max(peak, int(abs(values.astype("int32")).max()))
                    output.writeframes(values.tobytes())
            for converted in resampler.resample(None):
                samples += converted.samples
                values = converted.to_ndarray()
                peak = max(peak, int(abs(values.astype("int32")).max()))
                output.writeframes(values.tobytes())
        if samples == 0 or peak == 0:
            raise StudioError("The narration is empty or silent. Upload or generate a new clip.")
        if samples > 300 * 24000 or destination.stat().st_size > MAX_AUDIO_BYTES:
            raise StudioError("The prepared narration exceeds the supported audio limit.")
        return destination, {
            "mime": "audio/wav",
            "duration": samples / 24000,
            "sample_rate": 24000,
            "channels": 1,
            "preparation": "Reviewed as mono PCM WAV at 24 kHz; no speed or pitch changes.",
        }
    except StudioError:
        destination.unlink(missing_ok=True)
        raise
    except (av.error.FFmpegError, OSError, ValueError):
        destination.unlink(missing_ok=True)
        raise StudioError("The narration could not be decoded.") from None


def prepare_candidate(kind, data, media_dir):
    if kind not in {"image", "audio"}:
        raise StudioError("Only portraits and narration can be uploaded.")
    maximum = MAX_REFERENCE_BYTES if kind == "image" else MAX_AUDIO_UPLOAD_BYTES
    if not data or len(data) > maximum:
        raise StudioError(f"Use a nonempty file up to {maximum // (1024 * 1024)} MB.", 413)
    if kind == "image":
        path, metadata = prepare_image(io.BytesIO(data), media_dir)
    else:
        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            format_name = "wav"
        elif data.startswith(b"fLaC"):
            format_name = "flac"
        elif data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
            format_name = "mp3"
        else:
            raise StudioError("Use a WAV, MP3 or FLAC audio file.")
        path, metadata = prepare_audio(io.BytesIO(data), media_dir, format_name)
        if not 4 <= metadata["duration"] <= 300:
            path.unlink(missing_ok=True)
            raise StudioError("OmniHuman requires audio between 4 and 300 seconds.")
    return path, {**metadata, "origin": "upload"}


def collect_video(source, media_dir):
    destination = Path(media_dir) / f"{uuid4()}.mp4"
    if source.stat().st_size > MAX_VIDEO_BYTES:
        raise StudioError("The returned video exceeds this Studio's 750 MB download limit.")
    try:
        with av.open(str(source)) as container:
            if not container.streams.video:
                raise StudioError("The result has no video stream.")
            frame = next(container.decode(video=0), None)
            if frame is None:
                raise StudioError("The returned video has no decodable frames.")
            duration = float(container.duration or 0) / av.time_base
            metadata = {"mime": "video/mp4", "width": frame.width, "height": frame.height, "duration": duration}
        shutil.copyfile(source, destination)
        return destination, metadata
    except StudioError:
        raise
    except (av.error.FFmpegError, OSError, ValueError):
        destination.unlink(missing_ok=True)
        raise StudioError("The generated video could not be collected. Keep its task ID for recovery.") from None
