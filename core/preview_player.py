"""本地音频试听器。

试听只把乐谱音高渲染成内存 WAV 并交给 Windows 扬声器播放,不会调用
KeyboardDriver / EventPlayer,因此不会向游戏发送键盘或鼠标输入。
"""

import io
import math
import re
import struct
import sys
import threading
import wave

from PyQt6.QtCore import QObject, pyqtSignal


PREVIEW_CHUNK_MS = 80
PREVIEW_GAP_MS = 20
_SAMPLE_RATE = 22050
_NOTE_ID_RE = re.compile(r"^(high|mid|low)_([1-7])$")
_OCTAVE_OFFSETS = {"low": -1, "mid": 0, "high": 1}


def note_frequency(note_id: str, semitone: int = 0) -> float:
    """把存储格式的音符 ID 转为平均律频率。

    存储中的中音 1 以 C4 为基准;低/高音分别相差一个八度。
    """
    match = _NOTE_ID_RE.fullmatch(str(note_id).strip())
    if match is None:
        raise ValueError(f"无法试听未知音符: {note_id!r}")
    octave, pitch_text = match.groups()
    semitone = int(semitone or 0)
    if semitone not in (0, 1):
        raise ValueError(f"半音标记必须是 0 或 1: {semitone!r}")
    midi = 60 + _OCTAVE_OFFSETS[octave] * 12 + int(pitch_text) - 1 + semitone
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def note_frequencies(note: dict) -> list[float]:
    """返回一个谱面事件需要同时发出的频率;空列表表示休止符。"""
    note_ids = note.get("notes") or []
    semitone = note.get("semitone", 0)
    return [note_frequency(note_id, semitone) for note_id in note_ids]


def preview_duration_ms(note: dict, bpm: float) -> int:
    """按谱面时值和 BPM 计算试听事件时长。"""
    return max(1, int(round(float(note["dur"]) * 60000.0 / max(1.0, float(bpm)))))


def render_wav(frequencies: list[float], duration_ms: int) -> bytes:
    """生成单声道、16-bit PCM 内存 WAV,支持单音和简单和弦。"""
    sample_count = max(1, int(round(_SAMPLE_RATE * max(1, duration_ms) / 1000.0)))
    channels = max(1, len(frequencies))
    frames = bytearray(sample_count * 2)
    attack = max(1, int(_SAMPLE_RATE * 0.005))
    release = max(1, int(_SAMPLE_RATE * 0.008))

    for index in range(sample_count):
        envelope = min(1.0, index / attack, (sample_count - index) / release)
        if frequencies:
            sample = sum(
                math.sin(2.0 * math.pi * frequency * index / _SAMPLE_RATE)
                for frequency in frequencies
            ) / channels
            sample *= 0.32 * envelope
        else:
            sample = 0.0
        sample = max(-1.0, min(1.0, sample))
        struct.pack_into("<h", frames, index * 2, int(sample * 32767))

    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(frames)
    return stream.getvalue()


class PreviewPlayer(QObject):
    """在后台线程播放试听音频,并向 GUI 报告进度。"""

    started = pyqtSignal(int)  # 总事件数
    progress = pyqtSignal(int, int)  # 已完成事件数, 总事件数
    finished = pyqtSignal(bool)  # 自然结束 / 用户停止
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def play(self, notes, bpm=100, gap_ms=PREVIEW_GAP_MS, score_name="") -> bool:
        """开始试听;返回 False 表示已有试听正在播放。"""
        notes = [dict(note) for note in notes]
        if not notes:
            raise ValueError("没有可试听的音符")
        bpm = max(1.0, float(bpm))
        gap_ms = max(0.0, float(gap_ms))
        with self._lock:
            if self.is_playing:
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(notes, bpm, gap_ms, str(score_name)),
                daemon=True,
            )
            self._thread.start()
        self.started.emit(len(notes))
        return True

    def stop(self):
        """停止试听;分块播放保证正常情况下很快响应。"""
        self._stop_event.set()
        self._purge_windows_sound()

    def shutdown(self, join_timeout=1.0):
        self.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(join_timeout)

    def _purge_windows_sound(self):
        if sys.platform != "win32":
            return
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def _play_chunk(self, audio: bytes):
        import winsound

        winsound.PlaySound(audio, winsound.SND_MEMORY)

    def _run(self, notes, bpm, gap_ms, _score_name):
        normal = False
        try:
            if sys.platform != "win32":
                raise RuntimeError("试听功能目前仅支持 Windows 系统扬声器")
            for index, note in enumerate(notes):
                if self._stop_event.is_set():
                    break
                frequencies = note_frequencies(note)
                remaining_ms = preview_duration_ms(note, bpm)
                if frequencies:
                    interrupted = False
                    while remaining_ms > 0:
                        if self._stop_event.is_set():
                            interrupted = True
                            break
                        chunk_ms = min(PREVIEW_CHUNK_MS, remaining_ms)
                        self._play_chunk(render_wav(frequencies, chunk_ms))
                        remaining_ms -= chunk_ms
                    if interrupted:
                        break
                elif self._stop_event.wait(remaining_ms / 1000.0):
                    break
                self.progress.emit(index + 1, len(notes))
                if index + 1 < len(notes) and gap_ms > 0:
                    if self._stop_event.wait(gap_ms / 1000.0):
                        break
            normal = not self._stop_event.is_set()
        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            self._purge_windows_sound()
        self.finished.emit(normal)
