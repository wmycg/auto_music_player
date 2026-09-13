"""gui.disclaimer 模块测试:文案逐字断言 + 对话框交互/防绕过断言。

offscreen 平台运行,不依赖真实显示器。运行: python -m unittest tests.test_disclaimer
"""

import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QLabel, QCheckBox, QPushButton

from gui.disclaimer import (
    BTN_CONTINUE_TEXT,
    BTN_QUIT_TEXT,
    COUNTDOWN_SECONDS,
    DISCLAIMER_BODY,
    DISCLAIMER_OPEN_SOURCE,
    DISCLAIMER_SKIP_KEY,
    DISCLAIMER_TUTORIAL,
    DISCLAIMER_TITLE,
    RiskDisclaimerDialog,
    SKIP_CHECKBOX_TEXT,
    confirm_risk_disclaimer,
)

BANNED_TEXTS = ("不再提示", "跳过", "稍后决定")


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sync_count = 0

    def value(self, key, default=False):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.sync_count += 1


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class TestDisclaimerConstants(unittest.TestCase):
    def test_constants_match_spec_locked_values(self):
        self.assertEqual(DISCLAIMER_TITLE, "⚠️ 风险警示")
        self.assertIn("游戏账号封禁", DISCLAIMER_BODY)
        self.assertIn("免费开源", DISCLAIMER_OPEN_SOURCE)
        self.assertIn("作者联系方式", DISCLAIMER_OPEN_SOURCE)
        self.assertIn("试听当前乐谱", DISCLAIMER_TUTORIAL)
        self.assertEqual(BTN_CONTINUE_TEXT, "我已知晓并自愿承担全部风险，继续使用")
        self.assertEqual(BTN_QUIT_TEXT, "退出程序")

    def test_constants_non_empty(self):
        for value in (
            DISCLAIMER_TITLE,
            DISCLAIMER_BODY,
            DISCLAIMER_OPEN_SOURCE,
            DISCLAIMER_TUTORIAL,
            BTN_CONTINUE_TEXT,
            BTN_QUIT_TEXT,
            SKIP_CHECKBOX_TEXT,
        ):
            self.assertTrue(value)


class TestRiskDisclaimerDialog(unittest.TestCase):
    def setUp(self):
        self.dlg = RiskDisclaimerDialog()
        self.addCleanup(self.dlg.deleteLater)

    def _button(self, text):
        for btn in self.dlg.findChildren(QPushButton):
            if btn.text() == text:
                return btn
        raise AssertionError(f"按钮不存在: {text}")

    def test_dialog_is_modal(self):
        self.assertTrue(self.dlg.isModal())

    def test_continue_button_accepts(self):
        self.dlg._countdown_timer.stop()
        for _ in range(COUNTDOWN_SECONDS):
            self.dlg._countdown_tick()
        self._button(BTN_CONTINUE_TEXT).click()
        self.assertEqual(self.dlg.result(), RiskDisclaimerDialog.DialogCode.Accepted)

    def test_continue_button_is_locked_during_countdown(self):
        button = self._button(BTN_CONTINUE_TEXT)
        self.assertFalse(button.isEnabled())
        self.dlg.accept()
        self.assertEqual(self.dlg.result(), RiskDisclaimerDialog.DialogCode.Rejected)

    def test_skip_checkbox_is_present(self):
        checkbox = self.dlg.findChild(QCheckBox, "DisclaimerSkipCheckbox")
        self.assertIsNotNone(checkbox)
        self.assertEqual(checkbox.text(), SKIP_CHECKBOX_TEXT)

    def test_quit_button_rejects(self):
        self._button(BTN_QUIT_TEXT).click()
        self.assertEqual(self.dlg.result(), RiskDisclaimerDialog.DialogCode.Rejected)

    def test_close_event_normalizes_to_rejected(self):
        # 模拟标题栏 × / Alt+F4 路径:close() 触发 closeEvent
        self.dlg.close()
        self.assertEqual(self.dlg.result(), RiskDisclaimerDialog.DialogCode.Rejected)

    def test_exactly_two_clickable_buttons(self):
        buttons = self.dlg.findChildren(QPushButton)
        self.assertEqual(len(buttons), 2)
        self.assertEqual(
            sorted(b.text() for b in buttons),
            sorted([BTN_CONTINUE_TEXT, BTN_QUIT_TEXT]),
        )

    def test_no_bypass_widgets(self):
        texts = " ".join(lbl.text() for lbl in self.dlg.findChildren(QLabel))
        for banned in BANNED_TEXTS:
            self.assertNotIn(banned, texts)

    def test_body_label_shows_verbatim_text(self):
        body = self.dlg.findChild(QLabel, "DisclaimerBody")
        self.assertIsNotNone(body)
        self.assertEqual(body.text(), DISCLAIMER_BODY)


class TestConfirmRiskDisclaimer(unittest.TestCase):
    def test_returns_true_on_accepted(self):
        settings = MemorySettings()
        with patch.object(
            RiskDisclaimerDialog, "exec",
            lambda self: (
                self.skip_checkbox.setChecked(True),
                RiskDisclaimerDialog.DialogCode.Accepted,
            )[1],
        ):
            self.assertTrue(confirm_risk_disclaimer(settings=settings))
        self.assertTrue(settings.value(DISCLAIMER_SKIP_KEY))
        self.assertEqual(settings.sync_count, 1)

    def test_returns_false_on_rejected(self):
        settings = MemorySettings()
        with patch.object(
            RiskDisclaimerDialog, "exec",
            lambda self: RiskDisclaimerDialog.DialogCode.Rejected,
        ):
            self.assertFalse(confirm_risk_disclaimer(settings=settings))
        self.assertNotIn(DISCLAIMER_SKIP_KEY, settings.values)

    def test_saved_skip_preference_skips_dialog(self):
        settings = MemorySettings({DISCLAIMER_SKIP_KEY: True})
        with patch.object(
            RiskDisclaimerDialog,
            "__init__",
            side_effect=AssertionError("不应构造免责声明对话框"),
        ):
            self.assertTrue(confirm_risk_disclaimer(settings=settings))


if __name__ == "__main__":
    unittest.main()
