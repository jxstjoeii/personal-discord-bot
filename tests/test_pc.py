from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import pc
from assistant.config import Settings
from assistant.db import Database


def make_settings(folder: Path) -> Settings:
    return Settings(
        discord_token="t",
        owner_id=42,
        guild_id=None,
        anthropic_api_key="",
        model="claude-sonnet-5-5",
        timezone=ZoneInfo("America/Los_Angeles"),
        database_path=folder / "assistant.db",
        user_addons_path=folder / "user_addons",
        phone_token="",
        phone_port=8787,
        log_channel_id=None,
    )


class OpenCheckTests(unittest.TestCase):
    def test_direct_opens_are_caught(self) -> None:
        for command in [
            "Start-Process notepad",
            "start https://example.com",
            "ii C:\\Users",
            "Invoke-Item .",
            "explorer.exe C:\\",
            "saps calc",
            "[System.Diagnostics.Process]::Start('notepad')",
        ]:
            self.assertTrue(pc.opens_without_helper(command), command)

    def test_safe_commands_pass(self) -> None:
        for command in [
            "Open-Window -FilePath 'notepad'",
            "Get-PSDrive C",
            "Start-Service Spooler",
            "Restart-Computer -WhatIf",
            "Get-ChildItem $HOME\\Downloads # start here",
        ]:
            self.assertFalse(pc.opens_without_helper(command), command)


class ProcessTests(unittest.TestCase):
    def test_tasklist_and_game(self) -> None:
        names = pc.parse_tasklist(
            '"Overwatch.exe","1234","Console","1","2,000,000 K"\n"Discord.exe","5","Console","1","1 K"\n'
        )
        self.assertEqual(names, {"overwatch", "discord"})
        with tempfile.TemporaryDirectory() as folder:
            settings = make_settings(Path(folder))
            self.assertEqual(pc.running_game(settings, names), "Overwatch")
            self.assertIsNone(pc.running_game(settings, {"discord"}))


class ScriptTests(unittest.TestCase):
    def test_script_has_helper_and_command(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            script = pc.build_script(make_settings(Path(folder)), "Get-Date")
        self.assertIn("function Open-Window", script)
        self.assertIn("$PatriciaGames = @('Overwatch')", script)
        self.assertIn("\nGet-Date\n", script)

    def test_stderr_cleanup(self) -> None:
        raw = '#< CLIXML\n<Objs><S S="Error">Access is denied_x000D__x000A_</S></Objs>'
        self.assertEqual(pc._clean_stderr(raw).strip(), "Access is denied")

    def test_fix_plan(self) -> None:
        plan = {"goal": "g", "commands": [{"description": "a", "command": "x"}], "verify_command": "v"}
        self.assertIsNone(pc.fix_plan(plan, {"success": True, "fix_commands": []}))
        fix = pc.fix_plan(
            plan,
            {"success": False, "fix": "Try y", "fix_commands": [{"description": "b", "command": "y"}]},
        )
        self.assertEqual(fix["attempt"], 2)
        self.assertEqual(fix["verify_command"], "v")
        self.assertEqual(pc.normalize_steps([{"command": " "}, {"command": "a"}]), [{"description": "Step", "command": "a"}])


class TaskStoreTests(unittest.TestCase):
    def test_claim_runs_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            task = db.add_pc_task(42, "{}", 7)
            self.assertTrue(db.claim_pc_task(task, "pending", "running"))
            self.assertFalse(db.claim_pc_task(task, "pending", "running"))
            db.set_pc_task_message(task, 7, 99)
            self.assertEqual(db.get_pc_task(task)["message_id"], 99)
            db.close()


if __name__ == "__main__":
    unittest.main()
