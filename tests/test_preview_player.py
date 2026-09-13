"""本地试听器测试:钢琴 MIDI 映射、时值与兼容 WAV,不触发真实扬声器。"""

import io
import sys
import wave

import pytest

from core.preview_player import (
    MIDI_ACOUSTIC_GRAND_PIANO,
    _midi_message,
    note_frequencies,
    note_frequency,
    note_midi_number,
    note_midi_numbers,
    preview_duration_ms,
    render_wav,
    PreviewPlayer,
)


class FakeMidiOutput:
    def __init__(self):
        self.events = []

    def note_on(self, midi_note):
        self.events.append(("on", midi_note))

    def note_off(self, midi_note):
        self.events.append(("off", midi_note))

    def reset(self):
        self.events.append(("reset",))

    def close(self):
        self.events.append(("close",))


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


def test_numbered_notation_uses_natural_major_scale_midi_notes():
    assert [note_midi_number(f"mid_{number}") for number in range(1, 8)] == [
        60, 62, 64, 65, 67, 69, 71
    ]
    assert note_midi_number("mid_1", 1) == 61
    assert note_midi_numbers(
        {"notes": ["mid_1", "mid_3", "mid_5"], "dur": 1.0}
    ) == [60, 64, 67]


def test_general_midi_program_is_acoustic_grand_piano():
    assert MIDI_ACOUSTIC_GRAND_PIANO == 0
    assert _midi_message(0xC0, MIDI_ACOUSTIC_GRAND_PIANO) == 0xC0
    assert _midi_message(0x90, 60, 92) == 0x5C3C90


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


def test_preview_player_sends_midi_note_events_without_real_audio(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    player = PreviewPlayer()
    midi = FakeMidiOutput()
    player._create_midi_output = lambda: midi
    finished = []
    player.finished.connect(finished.append)

    player._run(
        [{"notes": ["mid_1", "mid_3", "mid_5"], "dur": 0.0}],
        120,
        0.0,
        "",
    )

    assert finished == [True]
    assert midi.events == [
        ("on", 60),
        ("on", 64),
        ("on", 67),
        ("off", 60),
        ("off", 64),
        ("off", 67),
        ("reset",),
        ("close",),
    ]


def test_preview_player_emits_finished_for_stop_without_audio(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    player = PreviewPlayer()
    player._create_midi_output = lambda: pytest.fail("已停止时不应打开 MIDI 音源")
    player._stop_event.set()
    finished = []
    player.finished.connect(finished.append)

    player._run([{"notes": ["mid_1"], "dur": 1.0}], 120, 0.0, "")

    assert finished == [False]


def test_stop_resets_active_midi_notes():
    player = PreviewPlayer()
    midi = FakeMidiOutput()
    player._midi_output = midi

    player.stop()

    assert player._stop_event.is_set()
    assert midi.events == [("reset",)]
