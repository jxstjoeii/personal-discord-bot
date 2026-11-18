from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import vision
from assistant.tools import AssistantTool, ToolContext, ToolResult, invoke_tool
from tests.test_pc import make_settings


def png(width: int, height: int) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", (width, height), (200, 30, 30, 128)).save(out, format="PNG")
    return out.getvalue()


class PrepareTests(unittest.TestCase):
    def test_big_photo_is_shrunk(self) -> None:
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        from PIL import Image

        picture = vision.prepare(png(4000, 3000), "image/png", "photo.png")
        self.assertEqual(picture.mime, "image/jpeg")
        self.assertEqual(max(Image.open(io.BytesIO(picture.data)).size), vision.MAX_SIDE)

    def test_not_a_picture(self) -> None:
        self.assertIsNone(vision.prepare(b"not an image" * 10, "application/pdf"))


class ChooseTests(unittest.TestCase):
    def test_choose(self) -> None:
        entries = [
            {"index": 1, "primary": True, "game": True, "discord": False, "path": None, "skipped": True},
            {"index": 2, "primary": False, "game": False, "discord": True, "path": "b.jpg"},
            {"index": 3, "primary": False, "game": False, "discord": False, "path": "c.jpg"},
        ]
        self.assertEqual([e["index"] for e in vision.choose(entries, "all")], [2, 3])
        self.assertEqual([e["index"] for e in vision.choose(entries, "discord")], [2])
        # The main screen is the game screen and was skipped, so something visible comes back.
        self.assertEqual([e["index"] for e in vision.choose(entries, "main")], [2])

    def test_capture_off_windows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            pictures, note = vision.capture(make_settings(Path(folder)))
        if not vision.pc.is_windows():
            self.assertEqual(pictures, [])
            self.assertIn("only works on the Windows PC", note)


class CaptureTests(unittest.TestCase):
    def test_game_screen_left_out(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        from unittest import mock

        monitors = [
            {"handle": 11, "box": (0, 0, 2560, 1440), "primary": True},
            {"handle": 22, "box": (2560, 0, 4480, 1080), "primary": False},
        ]
        grabbed = []

        def grab(bbox=None, all_screens=False):
            grabbed.append(bbox)
            return Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (10, 10, 10))

        game_or_discord = {("Overwatch",): 11, ("Discord", "DiscordPTB", "DiscordCanary"): 22}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(vision.pc, "is_windows", return_value=True), \
                mock.patch.object(vision, "_monitors", return_value=monitors), \
                mock.patch.object(vision, "_monitor_of", side_effect=lambda names: game_or_discord.get(tuple(names))), \
                mock.patch("PIL.ImageGrab.grab", grab):
            settings = make_settings(Path(folder))
            pictures, note = vision.capture(settings, "all")
            self.assertEqual(grabbed, [(2560, 0, 4480, 1080)])
            self.assertEqual(pictures[0].label, "Screen 2, has Discord")
            self.assertIn("game screen was left out", note)
            grabbed.clear()
            pictures, note = vision.capture(settings, "all", include_game=True)
            self.assertEqual(len(grabbed), 2)
            self.assertEqual(max(Image.open(io.BytesIO(pictures[0].data)).size), vision.MAX_SIDE)


class ToolResultTests(unittest.TestCase):
    def test_pictures_pass_through(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = make_settings(Path(folder))
            shot = vision.Picture(b"x", "image/jpeg", "Screen 1")
            tool = AssistantTool("look", "", {"type": "object", "properties": {}}, lambda ctx: ToolResult("Screens.", [shot]))
            result = invoke_tool({"look": tool}, ToolContext(1, settings, None), "look", "{}")
            self.assertIsInstance(result, ToolResult)
            self.assertEqual(str(result), "Screens.")
            self.assertEqual(result.images, [shot])


if __name__ == "__main__":
    unittest.main()
