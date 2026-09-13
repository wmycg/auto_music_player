"""Worker 生命周期测试：验证后台 worker 引用保持与清理，防止 GC 回收导致 segfault。

全部以 mock QThreadPool.start 捕获 worker + 手动 emit 信号的确定性方式验证，不依赖真实线程时序。
"""

import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.log_tab import PlayLogTab, LogWorker
from gui.log_detail_view import SessionDetailView, _ParseWorker


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "play_logs"
    d.mkdir()
    return str(d)


@pytest.fixture
def export_dir(tmp_path):
    d = tmp_path / "exports"
    d.mkdir()
    return str(d)


@pytest.fixture
def log_file(log_dir):
    path = os.path.join(log_dir, "test_session.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "session_start", "score_name": "test", "session_id": "s1"}) + "\n")
        f.write(json.dumps({"type": "note", "index": 0, "success": True}) + "\n")
        f.write(json.dumps({"type": "session_end", "completed": 1, "total": 1}) + "\n")
    return path


class _CapturedWorkers:
    """拦截 QThreadPool.start，捕获被派发的 worker 对象而不真正执行。"""

    def __init__(self):
        self.workers = []

    def __call__(self, worker, *args, **kwargs):
        self.workers.append(worker)


# ==================== 记录页 worker 引用保持与清理 ====================


class TestPlayLogTabWorkerLifecycle:
    """T1: 记录页 worker 引用保持与清理。"""

    def test_worker_held_in_active_workers_after_dispatch(self, log_dir, export_dir):
        """派发任务后 worker ∈ _active_workers（引用保持）。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            tab = PlayLogTab(log_dir=log_dir, export_dir=export_dir, sync_mode=False)
            tab.refresh_now()

        assert len(captured.workers) == 1
        worker = captured.workers[0]
        assert worker in tab._active_workers

    def test_worker_removed_after_signal_emit(self, log_dir, export_dir):
        """手动 emit finished 信号后 worker ∉ _active_workers（引用清理）。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            tab = PlayLogTab(log_dir=log_dir, export_dir=export_dir, sync_mode=False)
            tab.refresh_now()

        worker = captured.workers[0]
        assert worker in tab._active_workers

        worker.signals.finished.emit(LogWorker.TASK_REFRESH, {"logs": [], "cleanup": (0, 0)})

        assert worker not in tab._active_workers

    def test_callback_receives_payload_only(self, log_dir, export_dir):
        """包装回调转发 payload 至业务回调时仅收到单参数。"""
        received = []

        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            tab = PlayLogTab(log_dir=log_dir, export_dir=export_dir, sync_mode=False)
            original_on_refresh = tab._on_refresh_done
            tab._on_refresh_done = lambda payload: received.append(payload)
            tab.refresh_now()

        worker = captured.workers[0]
        test_payload = {"logs": [], "cleanup": (0, 0)}
        worker.signals.finished.emit(LogWorker.TASK_REFRESH, test_payload)

        assert len(received) == 1
        assert received[0] is test_payload

    def test_multiple_workers_coexist(self, log_dir, export_dir):
        """连续派发两个不同任务后两个 worker 均在集合中共存。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            tab = PlayLogTab(log_dir=log_dir, export_dir=export_dir, sync_mode=False)
            tab._dispatch(LogWorker.TASK_REFRESH, lambda: {"logs": []}, lambda p: None)
            tab._dispatch(LogWorker.TASK_EXPORT, lambda: {"path": "x"}, lambda p: None)

        assert len(captured.workers) == 2
        assert captured.workers[0] in tab._active_workers
        assert captured.workers[1] in tab._active_workers

        captured.workers[0].signals.finished.emit(LogWorker.TASK_REFRESH, {"logs": []})
        assert captured.workers[0] not in tab._active_workers
        assert captured.workers[1] in tab._active_workers

        captured.workers[1].signals.finished.emit(LogWorker.TASK_EXPORT, {"path": "x"})
        assert captured.workers[1] not in tab._active_workers

    def test_repeated_dispatch_no_leak(self, log_dir, export_dir):
        """连续触发 N 次同类任务且全部完成后 _active_workers 为空。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            tab = PlayLogTab(log_dir=log_dir, export_dir=export_dir, sync_mode=False)
            for _ in range(10):
                tab._task_running = False
                tab.refresh_now()
                captured.workers[-1].signals.finished.emit(
                    LogWorker.TASK_REFRESH, {"logs": [], "cleanup": (0, 0)}
                )

        assert len(tab._active_workers) == 0

    def test_sync_mode_no_workers(self, log_dir, export_dir):
        """sync_mode=True 时 _active_workers 始终为空。"""
        tab = PlayLogTab(log_dir=log_dir, export_dir=export_dir, sync_mode=True)
        tab.refresh_now()
        assert len(tab._active_workers) == 0


# ==================== 详情视图 worker 引用保持与清理 ====================


class TestDetailWorkerLifecycle:
    """T2: 详情视图 worker 引用保持与清理。"""

    def test_worker_held_after_load_session(self, log_dir, export_dir, log_file):
        """调用 load_session 后 worker ∈ _active_workers。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            view = SessionDetailView(log_dir=log_dir, sync_mode=False)
            view.load_session(log_file)

        assert len(captured.workers) == 1
        assert captured.workers[0] in view._active_workers

    def test_worker_removed_after_signal_emit(self, log_dir, export_dir, log_file):
        """手动 emit finished 后 worker ∉ _active_workers。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            view = SessionDetailView(log_dir=log_dir, sync_mode=False)
            view.load_session(log_file)

        worker = captured.workers[0]
        worker.signals.finished.emit({"events": [], "info": {}})

        assert worker not in view._active_workers

    def test_closed_view_still_cleans_reference(self, log_dir, export_dir, log_file):
        """视图标记 _closed=True 后触发完成信号，引用仍被清理。"""
        with patch.object(QThreadPool, "globalInstance") as mock_pool:
            mock_instance = mock_pool.return_value
            captured = _CapturedWorkers()
            mock_instance.start = captured

            view = SessionDetailView(log_dir=log_dir, sync_mode=False)
            view.load_session(log_file)

        worker = captured.workers[0]
        view._closed = True

        worker.signals.finished.emit({"events": [], "info": {}})

        assert worker not in view._active_workers

    def test_sync_mode_no_workers(self, log_dir, export_dir, log_file):
        """sync_mode=True 时 _active_workers 始终为空。"""
        view = SessionDetailView(log_dir=log_dir, sync_mode=True)
        view.load_session(log_file)
        assert len(view._active_workers) == 0