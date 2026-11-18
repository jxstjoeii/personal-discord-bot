"""Patricia's voice: speaks replies out loud with Kokoro's Heart voice.

It borrows the Kokoro install from the morning briefing
(%LOCALAPPDATA%\\MorningBriefing). If that's missing, it falls back to the
built-in Windows voice.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from assistant import pc
from assistant.config import ROOT

log = logging.getLogger(__name__)

SPEAK_SCRIPT = ROOT / "assistant" / "speak_kokoro.py"
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍]+"
)


def for_speech(text: str, limit: int = 600) -> str:
    """Strips Discord formatting and emoji so it reads naturally out loud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"<a?:\w+:\d+>", " ", text)          # custom Discord emoji
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](link)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"^\s*-#\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-•*]\s+", "", text, flags=re.M)
    text = text.replace("**", "").replace("__", "").replace("`", "").replace("*", "")
    text = _EMOJI.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…") + " The rest is in Discord."


def kokoro_paths(settings) -> tuple[Path, Path]:
    base = Path(os.getenv("LOCALAPPDATA", "")) / "MorningBriefing"
    python = Path(settings.kokoro_python) if settings.kokoro_python else base / "kokoro-venv" / "Scripts" / "python.exe"
    models = Path(settings.kokoro_models) if settings.kokoro_models else base / "kokoro"
    return python, models


def _play(path: str) -> None:
    import winsound

    winsound.PlaySound(path, winsound.SND_FILENAME)


def _kokoro(settings, text: str) -> bool:
    python, models = kokoro_paths(settings)
    if not (python.exists() and (models / "kokoro-v1.0.onnx").exists()):
        return False
    folder = tempfile.mkdtemp(prefix="patricia-voice-")
    text_file = os.path.join(folder, "say.txt")
    wav = os.path.join(folder, "say.wav")
    try:
        with open(text_file, "w", encoding="utf-8") as file:
            file.write(text)
        done = subprocess.run(
            [str(python), str(SPEAK_SCRIPT), "--text-file", text_file, "--out", wav,
             "--voice", settings.voice_name, "--model-dir", str(models)],
            capture_output=True,
            timeout=90,
            creationflags=pc.CREATE_NO_WINDOW,
        )
        if done.returncode != 0 or not os.path.exists(wav):
            log.warning("Kokoro failed: %s", done.stderr.decode("utf-8", "replace")[-300:])
            return False
        _play(wav)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Kokoro failed: %s", exc)
        return False
    finally:
        for name in (text_file, wav):
            try:
                os.remove(name)
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


def _windows_voice(text: str) -> bool:
    shell = pc.shell_path()
    if shell is None:
        return False
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$voice.Speak($env:PATRICIA_SAY)"
    )
    try:
        done = subprocess.run(
            [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=120,
            env={**os.environ, "PATRICIA_SAY": text},
            creationflags=pc.CREATE_NO_WINDOW,
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def speak(settings, text: str) -> bool:
    """Says the text out loud. Blocks until done. False if no voice worked."""
    if not pc.is_windows():
        return False
    spoken = for_speech(text)
    if not spoken:
        return False
    return _kokoro(settings, spoken) or _windows_voice(spoken)


def chime(kind: str = "listening") -> None:
    """A short Windows sound so you know she heard her name."""
    if not pc.is_windows():
        return
    try:
        import winsound

        sound = "SystemAsterisk" if kind == "listening" else "SystemExclamation"
        winsound.PlaySound(sound, winsound.SND_ALIAS)
    except Exception:
        pass
