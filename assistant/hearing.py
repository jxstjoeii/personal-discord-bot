"""Patricia's ears: speech to text with Whisper, running on this PC.

Audio never leaves the PC. Only the words Whisper hears are sent to Claude,
like a typed message. Models download once (from Hugging Face) the first time
they're used and are kept in data/whisper.
"""

from __future__ import annotations

import io
import logging
import threading

from assistant.config import ROOT

log = logging.getLogger(__name__)

MODEL_DIR = ROOT / "data" / "whisper"
# Helps Whisper spell names it would otherwise guess at.
HINT = "Patricia, Joeii, Overwatch, Kiriko, Puyallup."

_models: dict[str, object] = {}
_lock = threading.Lock()


class HearingUnavailable(RuntimeError):
    """Whisper isn't installed or couldn't load."""


def _model(name: str, device: str):
    key = f"{name}:{device}"
    with _lock:
        if key in _models:
            return _models[key]
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise HearingUnavailable("Whisper isn't installed yet. Run restart.ps1 in Patricia's folder.") from exc
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        compute = "float16" if device == "cuda" else "int8"
        try:
            model = WhisperModel(name, device=device, compute_type=compute, download_root=str(MODEL_DIR))
        except Exception as exc:
            if device == "cuda":
                log.warning("Whisper couldn't use the graphics card (%s), so it uses the CPU", exc)
                model = WhisperModel(name, device="cpu", compute_type="int8", download_root=str(MODEL_DIR))
            else:
                raise HearingUnavailable(f"Whisper couldn't load: {exc}") from exc
        _models[key] = model
        log.info("Whisper model %s ready", name)
        return model


def warm_up(name: str, device: str) -> None:
    """Load (and on first run, download) a model ahead of time."""
    try:
        _model(name, device)
    except Exception as exc:
        log.warning("Whisper warm-up failed: %s", exc)


def transcribe(audio, name: str, device: str = "cpu") -> str:
    """audio: file bytes (ogg, mp3, wav...) or a 16 kHz mono float32 numpy array."""
    model = _model(name, device)
    source = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio
    segments, _info = model.transcribe(
        source,
        language="en",
        beam_size=1,
        vad_filter=False,
        initial_prompt=HINT,
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()
