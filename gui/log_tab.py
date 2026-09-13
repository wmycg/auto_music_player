"""演奏记录页(顶层导航页):记录列表 + 页内二级详情 + 导出/删除/自动清理。

core LogManager 为唯一功能后端(GUI 侧独立实例,只读消费,不调用任何写侧接口);
列表加载/导出/删除统一经 LogWorker 后台执行,避免全文件解析冻结 UI;
sync_mode=True 时任务在调用线程同步执行,仅供测试注入,生产恒为 False。
"""

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.log_export import LogManager
from gui.log_detail_view import SessionDetailView
from gui.log_formatting import (
    format_anomaly_flag,
    format_completion,
    format_file_size,
)
from gui.log_texts import (
    ANOMALY_NONE_MARK,
    BTN_DELETE_TEXT,
    BTN_EXPORT_TEXT,
    BTN_VIEW_DETAIL_TEXT,
    CLEANUP_DONE_TEXT,
    CLEANUP_DONE_TITLE,
    DELETE_CONFIRM_BODY,
    DELETE_CONFIRM_TITLE,
    DELETE_DONE_TEXT,
    DELETE_DONE_TITLE,
    DELETE_PARTIAL_TEXT,
    EXPORT_FAIL_TEXT,
    EXPORT_FAIL_TITLE,
    EXPORT_FORMAT_ITEMS,
    EXPORT_FORMAT_LABEL,
    EXPORT_FORMAT_TITLE,
    EXPORT_SELECT_ONE_TEXT,
    EXPORT_SELECT_ONE_TITLE,
    EXPORT_SUCCESS_TEXT,
    EXPORT_SUCCESS_TITLE,
    LOAD_ERROR_TEXT,
    LOAD_ERROR_TITLE,
    LOG_EMPTY_TEXT,
    LOG_LOADING_TEXT,
    LOG_PAGE_SUBTITLE,
    LOG_PAGE_TITLE,
    LOG_TABLE_HEADERS,
    PLACEHOLDER_UNKNOWN,
)
from gui.theme import BRAND, INK_2, STATE_WARNING
from gui.widgets import AppDialog

_CLEANUP_MAX_AGE_DAYS = 7
_CLEANUP_MAX_TOTAL_MB = 50
_ITEM_FLAGS = (
    Qt.ItemFlag.ItemIsUserCheckable
    | Qt.ItemFlag.ItemIsEnabled
    | Qt.ItemFlag.ItemIsSelectable
)
_ITEM_FLAGS_PLAIN = _ITEM_FLAGS & ~Qt.ItemFlag.ItemIsUserCheckable


class _WorkerSignals(QObject):
    finished = pyqtSignal(str, object)


class LogWorker(QRunnable):
    """后台任务执行器:refresh / export / delete;全部异常折叠进 payload,信号必达。"""

    TASK_REFRESH = "refresh"
    TASK_EXPORT = "export"
    TASK_DELETE = "delete"

    def __init__(self, task_type, fn):
        super().__init__()
        self.task_type = task_type
        self.signals = _WorkerSignals()
        self._fn = fn
        self.setAutoDelete(True)

    def run(self):
        try:
            payload = self._fn()
        except Exception as e:
            payload = {"error": str(e)}
        self.signals.finished.emit(self.task_type, payload)


class PlayLogTab(QWidget):
    """演奏记录页:页内 QStackedWidget 承载"列表视图 ↔ 详情视图"两级切换。"""

    def __init__(
        self,
        parent=None,
        *,
        log_dir="data/play_logs",
        export_dir="data/exports",
        sync_mode=False,
    ):
        super().__init__(parent)
        self._manager = LogManager(log_dir, export_dir)
        self._sync_mode = sync_mode
        self._task_running = False
        self._active_workers = set()
        self._build_ui()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._page_stack = QStackedWidget()
        self._page_stack.setObjectName("LogPageStack")
        self._page_stack.addWidget(self._build_list_page())
        self._detail = SessionDetailView(sync_mode=self._sync_mode)
        self._detail.back_requested.connect(self._show_list)
        self._page_stack.addWidget(self._detail)
        root.addWidget(self._page_stack)

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel(LOG_PAGE_TITLE)
        title.setObjectName("PageTitle")
        subtitle = QLabel(LOG_PAGE_SUBTITLE)
        subtitle.setObjectName("PageSub")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch(1)
        layout.addLayout(header)

        btn_row = QHBoxLayout()
        self.detail_btn = QPushButton(BTN_VIEW_DETAIL_TEXT)
        self.detail_btn.setObjectName("BtnSecondary")
        self.detail_btn.clicked.connect(self._open_current_row_detail)
        self.export_btn = QPushButton(BTN_EXPORT_TEXT)
        self.export_btn.setObjectName("BtnSecondary")
        self.export_btn.clicked.connect(self._export_selected)
        self.delete_btn = QPushButton(BTN_DELETE_TEXT)
        self.delete_btn.setObjectName("BtnDanger")
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.detail_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._list_stack = QStackedWidget()
        self._list_stack.setObjectName("LogListStack")
        self.empty_label = QLabel(LOG_EMPTY_TEXT)
        self.empty_label.setObjectName("LogEmptyText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_stack.addWidget(self.empty_label)
        self._table = self._build_table()
        self._list_stack.addWidget(self._table)
        self._list_stack.setCurrentIndex(0)
        layout.addWidget(self._list_stack, 1)
        return page

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(LOG_TABLE_HEADERS))
        table.setObjectName("LogTable")
        table.setHorizontalHeaderLabels(LOG_TABLE_HEADERS)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 240)
        table.cellDoubleClicked.connect(lambda r, _c: self._open_row_detail(r))
        return table

    # ---------- 任务调度 ----------

    def _dispatch(self, task_type, fn, on_done):
        """任务派发:sync_mode 在调用线程同步执行(测试注入),否则投递线程池。"""
        if self._sync_mode:
            try:
                payload = fn()
            except Exception as e:
                payload = {"error": str(e)}
            on_done(payload)
            return
        worker = LogWorker(task_type, fn)
        self._active_workers.add(worker)

        def _on_finished(_task_type, payload):
            self._active_workers.discard(worker)
            on_done(payload)

        worker.signals.finished.connect(_on_finished)
        QThreadPool.globalInstance().start(worker)

    def _set_buttons_enabled(self, enabled: bool):
        for btn in (self.detail_btn, self.export_btn, self.delete_btn):
            btn.setEnabled(enabled)

    # ---------- 列表刷新(Q4:进入页面时清理+加载) ----------

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_now()

    def refresh_now(self):
        """显式触发"自动清理 → 列表加载"组合任务(单个任务避免并发遍历竞态)。"""
        if self._task_running:
            return
        self._task_running = True
        self._set_buttons_enabled(False)
        self._show_state_message(LOG_LOADING_TEXT)
        self._dispatch(LogWorker.TASK_REFRESH, self._do_refresh, self._on_refresh_done)

    def _do_refresh(self) -> dict:
        cleanup = self._manager.auto_cleanup(_CLEANUP_MAX_AGE_DAYS, _CLEANUP_MAX_TOTAL_MB)
        logs = self._manager.list_logs()
        return {"logs": logs, "cleanup": cleanup}

    def _on_refresh_done(self, payload: dict):
        self._task_running = False
        self._set_buttons_enabled(True)
        if payload.get("error"):
            AppDialog.show_error(self, LOAD_ERROR_TITLE, LOAD_ERROR_TEXT)
            self._show_state_message(LOG_EMPTY_TEXT)
            return
        logs = payload.get("logs") or []
        if not logs:
            self._show_state_message(LOG_EMPTY_TEXT)
        else:
            self._fill_table(logs)
            self._list_stack.setCurrentIndex(1)
        cleanup = payload.get("cleanup") or (0, 0)
        if cleanup[0] > 0:
            AppDialog.show_info(
                self,
                CLEANUP_DONE_TITLE,
                CLEANUP_DONE_TEXT.format(n=cleanup[0], m=cleanup[1]),
            )

    def _show_state_message(self, text: str):
        self.empty_label.setText(text)
        self._list_stack.setCurrentIndex(0)

    def _fill_table(self, logs: list):
        self._rows = list(logs)
        self._table.setRowCount(0)
        for entry in logs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            anomaly = int(entry.get("anomaly_count") or 0)
            cells = [
                (str(entry.get("score_name") or PLACEHOLDER_UNKNOWN), INK_2),
                (str(entry.get("started_at") or PLACEHOLDER_UNKNOWN), INK_2),
                (str(entry.get("duration") or PLACEHOLDER_UNKNOWN), INK_2),
                (format_completion(entry.get("completed"), entry.get("total")), BRAND),
                (format_anomaly_flag(anomaly) or ANOMALY_NONE_MARK, STATE_WARNING),
                (format_file_size(entry.get("file_size")), INK_2),
            ]
            for col, (text, color) in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setFlags(_ITEM_FLAGS)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    item.setData(Qt.ItemDataRole.UserRole, entry.get("path"))
                else:
                    item.setFlags(_ITEM_FLAGS_PLAIN)
                item.setForeground(QColor(color))
                self._table.setItem(row, col, item)

    # ---------- 详情切换(Q2:页内二级视图) ----------

    def _selected_paths(self) -> list:
        paths = []
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                paths.append(item.data(Qt.ItemDataRole.UserRole))
        return paths

    def _path_of_row(self, row: int):
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open_current_row_detail(self):
        row = self._table.currentRow()
        if row < 0:
            return
        self._open_row_detail(row)

    def _open_row_detail(self, row: int):
        path = self._path_of_row(row)
        if not path:
            return
        self._detail.load_session(path)
        self._page_stack.setCurrentIndex(1)

    def _show_list(self):
        """返回列表:列表控件未重建,滚动位置与勾选状态自然保持(spec 5.2.1.5)。"""
        self._page_stack.setCurrentIndex(0)

    # ---------- 删除(二次确认 + 部分失败如实提示) ----------

    def _delete_selected(self):
        if self._task_running:
            return
        paths = self._selected_paths()
        if not paths:
            return
        if not AppDialog.confirm(
            self, DELETE_CONFIRM_TITLE, DELETE_CONFIRM_BODY.format(n=len(paths))
        ):
            return
        self._task_running = True
        self._set_buttons_enabled(False)
        self._dispatch(
            LogWorker.TASK_DELETE,
            lambda: {"requested": len(paths), "deleted": self._manager.delete_logs(paths)},
            self._on_delete_done,
        )

    def _on_delete_done(self, payload: dict):
        self._task_running = False
        self._set_buttons_enabled(True)
        if payload.get("error"):
            AppDialog.show_error(self, DELETE_DONE_TITLE, str(payload["error"]))
            self.refresh_now()
            return
        requested = int(payload.get("requested") or 0)
        deleted = int(payload.get("deleted") or 0)
        if deleted >= requested:
            AppDialog.show_success(
                self, DELETE_DONE_TITLE, DELETE_DONE_TEXT.format(n=deleted)
            )
        else:
            AppDialog.show_warning(
                self,
                DELETE_DONE_TITLE,
                DELETE_PARTIAL_TEXT.format(n=deleted, m=requested - deleted),
            )
        self.refresh_now()

    # ---------- 导出(单条 + 格式选择 + 结果反馈) ----------

    def _export_selected(self):
        if self._task_running:
            return
        paths = self._selected_paths()
        if len(paths) > 1:
            AppDialog.show_info(self, EXPORT_SELECT_ONE_TITLE, EXPORT_SELECT_ONE_TEXT)
            return
        if not paths:
            return
        fmt = self._ask_export_format()
        if fmt is None:
            return
        path = paths[0]
        self._task_running = True
        self._set_buttons_enabled(False)
        self._dispatch(
            LogWorker.TASK_EXPORT,
            lambda: {"path": self._manager.export_log(path, fmt)},
            self._on_export_done,
        )

    def _ask_export_format(self):
        """弹出格式选择;返回格式值或 None(用户取消)。测试可注入覆写。"""
        displays = [display for _value, display in EXPORT_FORMAT_ITEMS]
        value_map = {display: value for value, display in EXPORT_FORMAT_ITEMS}
        choice, ok = QInputDialog.getItem(
            self, EXPORT_FORMAT_TITLE, EXPORT_FORMAT_LABEL, displays, 0, False
        )
        return value_map.get(choice) if ok else None

    def _on_export_done(self, payload: dict):
        self._task_running = False
        self._set_buttons_enabled(True)
        if payload.get("error") or not payload.get("path"):
            AppDialog.show_error(self, EXPORT_FAIL_TITLE, EXPORT_FAIL_TEXT)
            return
        AppDialog.show_info(
            self, EXPORT_SUCCESS_TITLE, EXPORT_SUCCESS_TEXT.format(path=payload["path"])
        )
