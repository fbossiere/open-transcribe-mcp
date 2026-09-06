import wave
from array import array
from pathlib import Path

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
AUDIO_PATH = FIXTURE_DIR / "open-transcribe-bilingual.wav"


def test_bilingual_audio_fixture_is_small_valid_pcm_with_deliberate_silence() -> None:
    with wave.open(str(AUDIO_PATH), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 22_050
        duration_seconds = audio.getnframes() / audio.getframerate()
        samples = array("h", audio.readframes(audio.getnframes()))

    assert 10 < duration_seconds < 45
    assert AUDIO_PATH.stat().st_size < 2_000_000

    longest_silence = 0
    current_silence = 0
    for sample in samples:
        if abs(sample) <= 8:
            current_silence += 1
            longest_silence = max(longest_silence, current_silence)
        else:
            current_silence = 0
    assert longest_silence / 22_050 >= 0.6


def test_bilingual_audio_fixture_has_known_reference_turns() -> None:
    reference = (FIXTURE_DIR / "reference-transcript.txt").read_text(encoding="utf-8")
    assert reference.count("SPEAKER_01 [en]") == 2
    assert reference.count("SPEAKER_02 [fr]") == 2
    assert "OpenTranscribe synthetic test recording" in reference
    assert "enregistrement de test synthétique" in reference
