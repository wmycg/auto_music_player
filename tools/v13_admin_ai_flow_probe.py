"""隔离复现 v1.3「管理员 + 外部 AI 粘贴 + 三角洲演奏 + 日志」完整链路。

本探针只使用临时数据库/日志目录和 FakeDriver，绝不会发送真实键鼠输入。
运行示例：
    python tools/v13_admin_ai_flow_probe.py --output-dir %TEMP%\amp-v13-probe
    # 管理员 PowerShell 中：
    python tools/v13_admin_ai_flow_probe.py --require-admin --output-dir %TEMP%\amp-v13-admin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.database import ScoreDB
from core.event_logger import configure_event_logger
from core.event_player import EventPlayer
from core.keymap import KeyMap
from core.player import Player
from core.profile import load_profiles
from gui.player_tab import PlayerTab
from gui.upload_tab import UploadTab
from gui.widgets import AppDialog
from main import is_admin


# 来自 v1.3 发布资产中出现过的粘连形态；新严格 AI 入口必须拒绝。
AMBIGUOUS_AI_SAMPLE = "3 2 3 2 3 5 2 1 5 5 7_1 1 2 2 1"
# 同一图谱片段按新提示词校正后的格式，并加入 Unicode 升号回归音。
VALID_AI_SAMPLE = "3 2 3 2 3 5 2 1 5 5 7, 1 1 2 2 1 1♯ 3'"

LEGACY_KEYMAP = {
    "high": list("QWERTYU"),
    "mid": list("ASDFGHJ"),
    "low": list("ZXCVBNM"),
}


class FakeDriver:
    """记录真实调用顺序，但不接触 SendInput。"""

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


class FakePreviewPlayer(QObject):
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

    def shutdown(self):
        self.stop()


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _wait_player(player: EventPlayer, app: QApplication, timeout: float = 15.0):
    deadline = time.time() + timeout
    while player.is_playing and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    if player.is_playing:
        raise TimeoutError("EventPlayer 在 15 秒内未结束")


def run_probe(output_dir: Path, require_admin: bool) -> dict:
    elevated = is_admin()
    if require_admin and not elevated:
        raise PermissionError("探针要求管理员权限，但当前进程不是 elevated token")

    output_dir.mkdir(parents=True, exist_ok=True)
    db = ScoreDB(str(output_dir / "scores.db"))
    log_dir = output_dir / "play_logs"
    logger = configure_event_logger(str(log_dir))
    driver = FakeDriver()
    event_player = EventPlayer(driver, logger=logger)
    legacy_player = Player(KeyMap(LEGACY_KEYMAP), driver=driver)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    preview = FakePreviewPlayer()

    dialogs = []
    AppDialog.show_warning = staticmethod(
        lambda _parent, title, message: dialogs.append(
            {"kind": "warning", "title": title, "message": message}
        )
    )
    AppDialog.show_success = staticmethod(
        lambda _parent, title, message: dialogs.append(
            {"kind": "success", "title": title, "message": message}
        )
    )
    AppDialog.show_error = staticmethod(
        lambda _parent, title, message: dialogs.append(
            {"kind": "error", "title": title, "message": message}
        )
    )

    upload = UploadTab(db, preview_player=preview)
    player_tab = None
    try:
        # 1) v1.3 历史 AI 粘连输出必须被阻断，不能静默入库。
        upload.raw_text.setPlainText(AMBIGUOUS_AI_SAMPLE)
        upload._parse()
        ambiguity_blocked = (
            upload.table.rowCount() == 0
            and any("AI 乐谱格式有歧义" == item["title"] for item in dialogs)
        )
        if not ambiguity_blocked:
            raise AssertionError("AI 粘连记号未被上传校对入口阻断")

        # 2) 校正后的 AI 输出走真实 UploadTab 解析和保存路径。
        upload.raw_text.setPlainText(VALID_AI_SAMPLE)
        upload._parse()
        if upload.table.rowCount() < 3:
            raise AssertionError("校正后的 AI 样本未进入校对表格")
        upload.name_edit.setText("v1.3 管理员 AI 回归样本")
        upload.bpm_spin.setValue(300)
        upload._save()
        saved = db.list_scores()
        if len(saved) != 1:
            raise AssertionError(f"预期保存 1 首乐谱，实际 {len(saved)}")
        score_id = int(saved[0]["id"])
        score = db.get_score(score_id)

        # 3) 走真实 PlayerTab 三秒倒计时入口和 Delta EventPlayer 分发。
        profiles = load_profiles(
            str(REPO_ROOT / "profiles"), fallback_keymap=LEGACY_KEYMAP
        )
        delta = next(p for p in profiles if p.id == "delta_force_harmonica")
        player_cfg = {
            "hold_ratio": 0.01,
            "gap_ms": 0,
            "modifier_settle_ms": 1,
            "modifier_release_ms": 1,
            "humanize": {"enabled": False},
            "focus_check": {"enabled": False},
        }
        player_tab = PlayerTab(
            db,
            legacy_player,
            player_cfg,
            profile=delta,
            profiles=profiles,
            event_player=event_player,
            preview_player=preview,
        )
        player_tab.refresh()
        player_tab.select_score(score_id)
        player_tab._play()
        if not player_tab._countdown_timer.isActive():
            raise AssertionError("三秒倒计时未启动")
        for _ in range(3):
            player_tab._countdown_tick()
        _wait_player(event_player, app)

        if not logger.log_path or not logger.log_path.exists():
            raise AssertionError(f"事件日志未落盘: {logger.last_error}")
        log_events = _read_jsonl(logger.log_path)
        modifier_down = [
            value
            for action, value in driver.events
            if action == "press_mouse"
        ]
        required_modifiers = {"left", "middle", "right"}
        if not required_modifiers.issubset(set(modifier_down)):
            raise AssertionError(f"三档/半音修饰事件不完整: {modifier_down}")
        if log_events[0].get("type") != "session_start":
            raise AssertionError("日志缺少 session_start")
        if log_events[-1].get("type") != "session_end":
            raise AssertionError("日志缺少 session_end")
        if log_events[-1].get("completed") != len(score["notes"]):
            raise AssertionError("日志完成音符数与入库乐谱不一致")

        return {
            "success": True,
            "is_admin": elevated,
            "require_admin": require_admin,
            "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
            "driver": "FakeDriver (no real keyboard/mouse input)",
            "ambiguous_ai_blocked": ambiguity_blocked,
            "saved_score_id": score_id,
            "saved_note_count": len(score["notes"]),
            "semitone_count": sum(bool(n.get("semitone")) for n in score["notes"]),
            "low_note_count": sum(
                any(note_id.startswith("low_") for note_id in n["notes"])
                for n in score["notes"]
            ),
            "high_note_count": sum(
                any(note_id.startswith("high_") for note_id in n["notes"])
                for n in score["notes"]
            ),
            "modifier_down": modifier_down,
            "log_path": str(logger.log_path),
            "log_event_count": len(log_events),
            "log_types": sorted({event.get("type") for event in log_events}),
            "session_completed": log_events[-1].get("completed"),
            "session_stopped_early": log_events[-1].get("stopped_early"),
            "dialogs": dialogs,
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
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-admin", action="store_true")
    args = parser.parse_args()

    args.output_dir = args.output_dir.resolve()
    result_path = args.output_dir / "probe-result.json"
    try:
        result = run_probe(args.output_dir, args.require_admin)
        exit_code = 0
    except Exception as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "success": False,
            "is_admin": is_admin(),
            "require_admin": args.require_admin,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**result, "result_path": str(result_path)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
