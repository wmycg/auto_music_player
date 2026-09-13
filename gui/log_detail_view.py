"""日志详情视图(页内二级):单会话摘要卡 + 可过滤事件时间线 + 分批渲染 + 返回动作。

解析经后台 worker 执行(sync_mode=True 时在调用线程同步执行,仅供测试注入);
解析一次后预生成全部行文本存内存,先渲染前 LOG_RENDER_CHUNK_SIZE 行,
"加载更多"逐批续载;类型过滤对已渲染行 O(n) setRowHidden,零重解析。
"""

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.log_export import get_session_info, read_jsonl_log
from gui.log_texts import (
    BTN_BACK_TEXT,
    BTN_LOAD_MORE_TEXT,
    EVENT_TYPE_LABELS,
    EXPORT_ALL_FILTER_TEXT,
    PLACEHOLDER_UNKNOWN,
)
from gui.log_formatting import format_event_row, format_summary_pairs
from gui.theme import BRAND, INK, INK_2

LOG_RENDER_CHUNK_SIZE = 2000
FILTER_ALL = "all"


class _WorkerSignals(QObject):
    finished = pyqtSignal(object)


class _ParseWorker(QRunnable):
    """后台解析单个会话日志;全部异常折叠进结果 payload,保证信号必达。"""

    def __init__(self, fn):
        super().__init__()
        self.signals = _WorkerSignals()
        self._fn = fn
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self._fn()
        except Exception as e:
            result = {"error": str(e)}
        self.signals.finished.emit(result)


class SessionDetailView(QWidget):
    """单会话日志详情二级视图;由 PlayLogTab 组合,返回切换动作由其执行。"""

    back_requested = pyqtSignal()

    def __init__(self, parent=None, *, log_dir="data/play_logs", sync_mode=False):
        super().__init__(parent)
        self._log_dir = log_dir
        self._sync_mode = sync_mode
        self._rows = []  # [(event_type, row_text)],按文件(时间)正序
        self._rendered_count = 0
        self._filter = FILTER_ALL
        self._closed = False
        self._active_workers = set()
        self._build_ui()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        self.back_btn = QPushButton(BTN_BACK_TEXT)
        self.back_btn.setObjectName("BtnSecondary")
        self.back_btn.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_btn)
        self.title_label = QLabel("")
        self.title_label.setObjectName("LogDetailTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)
        root.addLayout(header)

        card = QFrame()
        card.setObjectName("LogSummaryCard")
        self.summary_grid = QGridLayout(card)
        self.summary_grid.setContentsMargins(20, 16, 20, 16)
        self.summary_grid.setHorizontalSpacing(32)
        self.summary_grid.setVerticalSpacing(8)
        root.addWidget(card)

        filter_row = QHBoxLayout()
        filter_label = QLabel("事件类型")
        filter_label.setObjectName("SectionSubtitle")
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("LogFilterCombo")
        self.filter_combo.addItem(EXPORT_ALL_FILTER_TEXT, FILTER_ALL)
        for etype, label in EVENT_TYPE_LABELS.items():
            self.filter_combo.addItem(label, etype)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(filter_label)
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch(1)
        root.addLayout(filter_row)

        self.timeline = QListWidget()
        self.timeline.setObjectName("LogTimelineList")
        self.timeline.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        root.addWidget(self.timeline, 1)

        self.load_more_btn = QPushButton(BTN_LOAD_MORE_TEXT)
        self.load_more_btn.setObjectName("BtnSecondary")
        self.load_more_btn.clicked.connect(self._render_next_chunk)
        self.load_more_btn.hide()
        root.addWidget(self.load_more_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._fill_summary([(PLACEHOLDER_UNKNOWN, PLACEHOLDER_UNKNOWN)])

    # ---------- 数据加载 ----------

    def load_session(self, log_path: str):
        """加载单会话日志;文件可不完整(演奏中),解析失败呈占位态,不抛出。"""
        self._rows = []
        self._rendered_count = 0
        self._filter = FILTER_ALL
        self.filter_combo.blockSignals(True)
        self.filter_combo.setCurrentIndex(0)
        self.filter_combo.blockSignals(False)
        self.timeline.clear()
        self.load_more_btn.hide()
        self.title_label.setText(log_path)

        if self._sync_mode:
            self._apply_parse_result(self._parse(log_path))
            return

        worker = _ParseWorker(lambda: self._parse(log_path))
        self._active_workers.add(worker)

        def _on_finished(payload):
            self._active_workers.discard(worker)
            self._apply_parse_result(payload)

        worker.signals.finished.connect(_on_finished)
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _parse(log_path: str) -> dict:
        events = read_jsonl_log(log_path)
        info = get_session_info(events)
        return {"events": events, "info": info}

    def _apply_parse_result(self, payload: dict):
        if self._closed:
            return
        if not isinstance(payload, dict) or payload.get("error"):
            error = payload.get("error") if isinstance(payload, dict) else "未知错误"
            self.title_label.setText(f"{PLACEHOLDER_UNKNOWN}（{error}）")
            self._fill_summary([(PLACEHOLDER_UNKNOWN, PLACEHOLDER_UNKNOWN)])
            return
        events = payload.get("events") or []
        info = payload.get("info") or {}
        self.title_label.setText(str(info.get("score_name") or PLACEHOLDER_UNKNOWN))
        self._fill_summary(format_summary_pairs(info))
        self._rows = [
            (str(e.get("type", "")), format_event_row(e)) for e in events
        ]
        self._rendered_count = 0
        self._render_next_chunk()

    def _fill_summary(self, pairs):
        """清空摘要卡并按键值对渲染(两列流式布局)。"""
        while self.summary_grid.count():
            item = self.summary_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        per_col = (len(pairs) + 1) // 2
        for i, (label, value) in enumerate(pairs):
            row, col = i % per_col, (i // per_col) * 2
            lab = QLabel(label)
            lab.setStyleSheet(f"color: {INK_2}; font-size: 12px;")
            val = QLabel(value)
            val.setStyleSheet(f"color: {INK}; font-size: 13px; font-weight: 600;")
            val.setWordWrap(True)
            self.summary_grid.addWidget(lab, row, col)
            self.summary_grid.addWidget(val, row, col + 1)

    # ---------- 渲染与过滤 ----------

    def _render_next_chunk(self):
        start = self._rendered_count
        end = min(start + LOG_RENDER_CHUNK_SIZE, len(self._rows))
        for etype, text in self._rows[start:end]:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, etype)
            if not self._type_visible(etype):
                item.setHidden(True)
            self.timeline.addItem(item)
        self._rendered_count = end
        self.load_more_btn.setVisible(self._rendered_count < len(self._rows))

    def _type_visible(self, etype: str) -> bool:
        return self._filter in (None, FILTER_ALL) or etype == self._filter

    def set_type_filter(self, event_type):
        """按类型过滤已渲染行(None/"all" 表示全部);零重解析。"""
        self._filter = FILTER_ALL if event_type in (None, FILTER_ALL) else event_type
        for i in range(self.timeline.count()):
            item = self.timeline.item(i)
            item.setHidden(not self._type_visible(item.data(Qt.ItemDataRole.UserRole)))

    def _on_filter_changed(self):
        self.set_type_filter(self.filter_combo.currentData())

    def closeEvent(self, event):
        self._closed = True
        super().closeEvent(event)