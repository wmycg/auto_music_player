"""本地试听器测试:音高映射、时值计算和 WAV 渲染,不触发真实扬声器。"""

import io
import sys
import wave

import pytest

from core.preview_player import (
    note_frequencies,
    note_frequency,
    preview_duration_ms,
    render_wav,
    PreviewPlayer,
)


def test_note_frequency_uses_c4_as_middle_one():
    assert note_frequency("mid_1") == pytest.approx(261.6256, rel=1e-4)
    assert note_frequency("high_1") == pytest.approx(523.2511, rel=1e-4)
    assert note_frequency("low_1") == pytest.approx(130.8128, rel=1e-4)


def test_semitone_and_chord_frequencies():
    assert note_frequency("mid_1", 1) == pytest.approx(277.1826, rel=1e-4)
    frequencies = note_frequencies(
        {"notes": ["mid_1", "mid_3", "mid_5"], "dur": 1.0}
    )
    assert len(frequencies) == 3
    assert frequencies[0] < frequencies[1] < frequencies[2]


def test_rest_has_no_frequency():
    assert note_frequencies({"notes": [], "dur": 1.0}) == []


def test_invalid_note_is_rejected():
    with pytest.raises(ValueError, match="未知音符"):
        note_frequency("mid_8")


def test_preview_duration_uses_bpm_and_never_returns_zero():
    assert preview_duration_ms({"dur": 1.0}, 120) == 500
    assert preview_duration_ms({"dur": 0.0}, 120) == 1


def test_render_wav_returns_playable_pcm_wave():
    audio = render_wav([note_frequency("mid_1")], 40)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22050
        assert wav.getnframes() > 0


def test_preview_player_emits_finished_for_natural_end_without_audio(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    player = PreviewPlayer()
    player._play_chunk = lambda _audio: None
    finished = []
    player.finished.connect(finished.append)

    player._run([{"notes": ["mid_1"], "dur": 0.0}], 120, 0.0, "")

    assert finished == [True]


def test_preview_player_emits_finished_for_stop_without_audio(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    player = PreviewPlayer()
    player._stop_event.set()
    finished = []
    player.finished.connect(finished.append)

    player._run([{"notes": ["mid_1"], "dur": 1.0}], 120, 0.0, "")

    assert finished == [False]
