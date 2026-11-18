from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import speaking, wake
from assistant.db import Database
from assistant.wake import BLOCK, RATE, Segmenter, WakeListener, split_wake
from tests.test_pc import make_settings


def blocks(seconds: float, level: float) -> list:
    count = int(seconds * RATE / BLOCK)
    rng = np.random.default_rng(1)
    return [(rng.standard_normal(BLOCK) * level).astype("float32") for _ in range(count)]


class WakeTests(unittest.TestCase):
    def test_split_wake(self) -> None:
        self.assertEqual(split_wake("Hey Patricia, what's the weather?"), (True, "what's the weather"))
        self.assertEqual(split_wake("Hey, Patricia."), (True, ""))
        self.assertEqual(split_wake("okay patrisha set a timer"), (True, "set a timer"))
        self.assertEqual(split_wake("I told Patricia about it"), (False, ""))
        self.assertEqual(split_wake(""), (False, ""))

    def test_segmenter_finds_one_clip(self) -> None:
        segmenter = Segmenter()
        clips = []
        for block in blocks(1.0, 0.001) + blocks(1.2, 0.2) + blocks(1.2, 0.001):
            clip = segmenter.feed(block)
            if clip is not None:
                clips.append(clip)
        self.assertEqual(len(clips), 1)
        self.assertGreater(len(clips[0]) / RATE, 1.2)   # speech plus a little before and after
        self.assertLess(len(clips[0]) / RATE, 2.6)

    def test_segmenter_ignores_clicks(self) -> None:
        segmenter = Segmenter()
        found = [segmenter.feed(b) for b in blocks(0.5, 0.001) + blocks(0.06, 0.3) + blocks(1.5, 0.001)]
        self.assertTrue(all(c is None for c in found))


class HandleTests(unittest.TestCase):
    def make(self, quick: str, full: str, follow: str = ""):
        settings = make_settings(Path(tempfile.mkdtemp()))
        asked = []
        listener = WakeListener(settings, lambda text: asked.append(text) or "It's 52 degrees.", lambda: False)
        said = {"tiny.en": quick, "small.en": full}
        listener._transcribe = lambda clip, model: said[model]
        listener._follow_up = lambda stream: follow
        return listener, asked

    def test_name_and_request_in_one_breath(self) -> None:
        listener, asked = self.make("Hey Patricia what's the weather", "Hey Patricia, what's the weather?")
        with mock.patch.object(speaking, "speak") as speak:
            listener._handle(np.zeros(RATE, "float32"), None)
        self.assertEqual(asked, ["what's the weather"])
        speak.assert_called_once()
        self.assertEqual(speak.call_args[0][1], "It's 52 degrees.")

    def test_name_then_pause(self) -> None:
        listener, asked = self.make("Hey Patricia.", "Hey Patricia.", follow="remind me at 5")
        with mock.patch.object(speaking, "speak"), mock.patch.object(speaking, "chime") as chime:
            listener._handle(np.zeros(RATE, "float32"), None)
        chime.assert_called_once()
        self.assertEqual(asked, ["remind me at 5"])

    def test_other_talk_is_ignored(self) -> None:
        listener, asked = self.make("pass me the salt", "pass me the salt")
        with mock.patch.object(speaking, "speak") as speak:
            listener._handle(np.zeros(RATE, "float32"), None)
        self.assertEqual(asked, [])
        speak.assert_not_called()


class SpeechTextTests(unittest.TestCase):
    def test_for_speech(self) -> None:
        text = "☀️ **Good morning!** It's 44 F.\n- Bring a jacket 🧥\nSee [the forecast](https://x.y)."
        self.assertEqual(speaking.for_speech(text), "Good morning! It's 44 F. Bring a jacket See the forecast.")
        long = "This is a sentence. " * 60
        out = speaking.for_speech(long, limit=100)
        self.assertTrue(out.endswith("The rest is in Discord."))
        self.assertLess(len(out), 140)


class PrefTests(unittest.TestCase):
    def test_prefs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            self.assertEqual(db.get_pref("listening", "off"), "off")
            db.set_pref("listening", "on")
            db.set_pref("listening", "off")
            self.assertEqual(db.get_pref("listening"), "off")
            db.close()


if __name__ == "__main__":
    unittest.main()
