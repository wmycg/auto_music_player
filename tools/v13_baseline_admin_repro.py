"""在干净 v1.3 源码副本中复现 AI 粘连谱 + Delta 日志缺失。

目标源码通过 --baseline-root 指定。本脚本只用临时数据库与 FakeDriver，
不发送真实键鼠输入；返回 0 表示成功观察到旧缺陷，而不是功能正常。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(baseline_root: Path, output_dir: Path, require_admin: bool) -> dict:
    elevated = _is_admin()
    if require_admin and not elevated:
        raise PermissionError("复现要求管理员权限，但当前进程不是 elevated token")
    if not (baseline_root / "version.txt").exists():
        raise FileNotFoundError(f"不是有效源码副本: {baseline_root}")

    # 必须在导入任何项目模块前把干净 v1.3 放到搜索路径首位。
    sys.path.insert(0, str(baseline_root))
    os.chdir(baseline_root)

    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication

    import core.event_logger as event_logger_mod
    from core.database import ScoreDB
    from core.event_logger import EventLogger
    from core.event_player import EventPlayer
    from core.keymap import KeyMap
    from core.parser import parse_jianpu
    from core.player import Player
    from core.profile import load_profiles
    from gui.player_tab import PlayerTab
    from gui.upload_tab import UploadTab
    from gui.widgets import AppDialog

    class FakeDriver:
        def __init__(self):
            self.events = []
            self.lock = threading.Lock()

        def _record(self, action, value):
            with self.lock:
                self.events.append((action, value))

        def press_key(self, key):
            self._record("press_key", key)

        def release_key(self, key):
            self._record("release_key", key)

        def press_mouse(self, button):
            self._record("press_mouse", button)

        def release_mouse(self, button):
            self._record("release_mouse", button)

        def press_chord(self, keys):
            self._record("press_chord", tuple(keys))

        def release_chord(self, keys):
            self._record("release_chord", tuple(keys))

        def panic_release(self, keys, mouse=()):
            self._record("panic_release", (tuple(keys), tuple(mouse)))

    class FakePreview(QObject):
        finished = pyqtSignal(bool)
        error_occurred = pyqtSignal(str)

        def __init__(self):
            super().__init__()
            self.is_playing = False

        def play(self, *_args, **_kwargs):
            self.is_playing = True
            return True

        def stop(self):
            self.is_playing = False

    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_dir / "play_logs"
    db = ScoreDB(str(output_dir / "scores.db"))
    event_logger_mod._event_logger_instance = EventLogger(str(log_dir))
    driver = FakeDriver()
    event_player = EventPlayer(driver)
    keymap_dict = {
        "high": list("QWERTYU"),
        "mid": list("ASDFGHJ"),
        "low": list("ZXCVBNM"),
    }
    legacy_player = Player(KeyMap(keymap_dict), driver=driver)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    preview = FakePreview()
    AppDialog.show_warning = staticmethod(lambda *_args, **_kwargs: None)
    AppDialog.show_success = staticmethod(lambda *_args, **_kwargs: None)
    AppDialog.show_error = staticmethod(lambda *_args, **_kwargs: None)

    upload = UploadTab(db, preview_player=preview)
    player_tab = None
    try:
        # 旧解析器把 Unicode 升号作为垃圾跳过，把 7_1 静默拆为两个自然音。
        sharp_notes, sharp_errors = parse_jianpu("1♯", collect=True)
        joined_notes, joined_errors = parse_jianpu("7_1", collect=True)

        upload.raw_text.setPlainText("7_1")
        upload._parse()
        table_rows = upload.table.rowCount()
        upload.name_edit.setText("v1.3 缺陷复现")
        upload.bpm_spin.setValue(300)
        upload._save()
        score_id = int(db.list_scores()[0]["id"])
        score = db.get_score(score_id)

        profiles = load_profiles(
            str(baseline_root / "profiles"), fallback_keymap=keymap_dict
        )
        delta = next(p for p in profiles if p.id == "delta_force_harmonica")
        player_tab = PlayerTab(
            db,
            legacy_player,
            {
                "hold_ratio": 0.01,
                "gap_ms": 0,
                "modifier_settle_ms": 1,
                "modifier_release_ms": 1,
                "humanize": {"enabled": False},
                "focus_check": {"enabled": False},
            },
            profile=delta,
            profiles=profiles,
            event_player=event_player,
            preview_player=preview,
        )
        player_tab.refresh()
        player_tab.select_score(score_id)
        player_tab._play()
        for _ in range(3):
            player_tab._countdown_tick()
        deadline = time.time() + 10
        while event_player.is_playing and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        if event_player.is_playing:
            raise TimeoutError("旧 EventPlayer 未结束")

        log_files = list(log_dir.glob("*.jsonl")) if log_dir.exists() else []
        modifier_down = [
            value for action, value in driver.events if action == "press_mouse"
        ]
        observations = {
            "unicode_sharp_lost": bool(sharp_errors)
            and not sharp_notes[0].get("semitone"),
            "joined_ai_had_no_error": joined_errors == [],
            "joined_ai_table_rows": table_rows,
            "stored_notes": score["notes"],
            "stored_low_note_count": sum(
                any(note_id.startswith("low_") for note_id in note["notes"])
                for note in score["notes"]
            ),
            "modifier_down": modifier_down,
            "event_log_files": len(log_files),
        }
        reproduced = (
            observations["unicode_sharp_lost"]
            and observations["joined_ai_had_no_error"]
            and observations["joined_ai_table_rows"] == 2
            and observations["stored_low_note_count"] == 0
            and "left" not in observations["modifier_down"]
            and observations["event_log_files"] == 0
        )
        if not reproduced:
            raise AssertionError(f"没有完整观察到旧缺陷: {observations}")
        return {
            "bug_reproduced": True,
            "is_admin": elevated,
            "require_admin": require_admin,
            "baseline_version": (baseline_root / "version.txt").read_text(
                encoding="utf-8"
            ).strip(),
            "baseline_root": str(baseline_root),
            "driver": "FakeDriver (no real keyboard/mouse input)",
            **observations,
        }
    finally:
        event_player.shutdown()
        legacy_player.shutdown()
        if player_tab is not None:
            player_tab._focus_timer.stop()
            timer = getattr(player_tab, "_countdown_timer", None)
            if timer is not None:
                timer.stop()
            player_tab.deleteLater()
        upload.deleteLater()
        db.conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-admin", action="store_true")
    args = parser.parse_args()
    args.baseline_root = args.baseline_root.resolve()
    args.output_dir = args.output_dir.resolve()
    result_path = args.output_dir / "baseline-repro-result.json"
    try:
        result = run(args.baseline_root, args.output_dir, args.require_admin)
        code = 0
    except Exception as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "bug_reproduced": False,
            "is_admin": _is_admin(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        code = 1
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**result, "result_path": str(result_path)}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
