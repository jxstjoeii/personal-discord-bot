"""'Hey Patricia': listens on the PC microphone for her name, then for a request.

Everything here runs on this PC. Speech is cut into short clips by loudness,
each clip is checked for "hey Patricia" with a tiny Whisper model, and only
then is the request transcribed and sent to Claude as text. Nothing is
recorded to disk. The microphone is only open while listening is switched on.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable

from assistant import hearing, speaking

log = logging.getLogger(__name__)

RATE = 16000
BLOCK = 480                 # 30 ms
START_BLOCKS = 3            # 90 ms of sound starts a clip
END_SILENCE = 0.8           # seconds of quiet ends a clip
MAX_CLIP = 15.0             # seconds
MIN_CLIP = 0.35             # seconds
PRE_ROLL = 10               # blocks kept from before the sound started
FOLLOW_UP_WAIT = 7.0        # seconds to wait for the request after "hey Patricia"

WAKE = re.compile(
    r"\b(?:hey|hi|hay|okay|ok|yo)\b[\s,.!-]*(?:patricia|patrisha|patrishia|patritia|petricia|tricia|trisha)\b",
    re.IGNORECASE,
)


def split_wake(text: str) -> tuple[bool, str]:
    """(heard her name, the request after it)."""
    match = WAKE.search(text or "")
    if not match:
        return False, ""
    rest = text[match.end():].strip(" ,.!?-")
    return True, rest


class Segmenter:
    """Cuts a stream of 30 ms blocks into speech clips, using loudness."""

    def __init__(self) -> None:
        self.floor = 0.004
        self.loud_run = 0
        self.quiet_time = 0.0
        self.active = False
        self.clip: list = []
        self.before: deque = deque(maxlen=PRE_ROLL)

    def feed(self, block):
        """Returns a finished clip (numpy array) or None."""
        import numpy as np

        level = float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0
        threshold = max(self.floor * 3.0, 0.008)
        loud = level > threshold
        seconds = len(block) / RATE
        if not self.active:
            self.floor = 0.97 * self.floor + 0.03 * min(level, 0.05)
            self.before.append(block)
            self.loud_run = self.loud_run + 1 if loud else 0
            if self.loud_run >= START_BLOCKS:
                self.active = True
                self.clip = list(self.before)
                self.quiet_time = 0.0
            return None
        self.clip.append(block)
        self.quiet_time = 0.0 if loud else self.quiet_time + seconds
        length = sum(len(b) for b in self.clip) / RATE
        if self.quiet_time >= END_SILENCE or length >= MAX_CLIP:
            clip = np.concatenate(self.clip)
            self.active = False
            self.clip = []
            self.loud_run = 0
            self.before.clear()
            if len(clip) / RATE >= MIN_CLIP:
                return clip
        return None


class WakeListener:
    """Runs in its own thread while listening is on."""

    def __init__(self, settings, on_request: Callable[[str], str], paused: Callable[[], bool]):
        self.settings = settings
        self.on_request = on_request
        self.paused = paused
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.problem = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.problem = ""
        self._thread = threading.Thread(target=self._run, name="hey-patricia", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -------------------------------------------------------------- loop --

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:
            self.problem = f"The microphone library isn't installed yet ({exc}). Run restart.ps1."
            log.warning(self.problem)
            return
        hearing.warm_up(self.settings.wake_model, self.settings.whisper_device)
        hearing.warm_up(self.settings.whisper_model, self.settings.whisper_device)
        device = self.settings.mic_device or None
        try:
            with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, device=device) as stream:
                log.info("Hey Patricia is listening")
                self._listen(stream)
        except Exception as exc:
            self.problem = f"I couldn't open the microphone: {exc}"
            log.warning(self.problem)
        finally:
            log.info("Hey Patricia stopped listening")

    def _listen(self, stream) -> None:
        segmenter = Segmenter()
        while not self._stop.is_set():
            block, _overflow = stream.read(BLOCK)
            clip = segmenter.feed(block[:, 0])
            if clip is None:
                continue
            if self.paused():
                continue
            try:
                self._handle(clip, stream)
            except Exception:
                log.exception("Handling a voice request failed")
            segmenter = Segmenter()  # Start fresh after talking or speaking.

    def _transcribe(self, clip, model: str) -> str:
        return hearing.transcribe(clip, model, self.settings.whisper_device)

    def _handle(self, clip, stream) -> None:
        quick = self._transcribe(clip, self.settings.wake_model)
        heard, _ = split_wake(quick)
        if not heard:
            return
        full = self._transcribe(clip, self.settings.whisper_model)
        heard_full, request = split_wake(full)
        if not heard_full:
            _, request = split_wake(quick)
        if not request:
            speaking.chime("listening")
            request = self._follow_up(stream)
        if not request:
            return
        log.info("Heard a voice request")
        answer = self.on_request(request)
        if self.settings.voice_replies and answer:
            speaking.speak(self.settings, answer)

    def _follow_up(self, stream) -> str:
        """After 'hey Patricia' on its own, waits a few seconds for the request."""
        segmenter = Segmenter()
        deadline = time.monotonic() + FOLLOW_UP_WAIT
        while time.monotonic() < deadline and not self._stop.is_set():
            block, _overflow = stream.read(BLOCK)
            clip = segmenter.feed(block[:, 0])
            if clip is not None:
                return self._transcribe(clip, self.settings.whisper_model).strip()
        return ""
