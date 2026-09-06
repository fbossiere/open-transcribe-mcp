# Synthetic bilingual audio fixture

`open-transcribe-bilingual.wav` is a project-owned synthetic recording generated offline with
eSpeak NG 1.51. It contains two distinct synthetic voices, alternating English and French, with
0.7-second silence intervals. It contains no recording of a real person and no sensitive content.

The expected words and speaker turns are in `reference-transcript.txt`. Provider punctuation,
capitalization, language labels, timestamps, and diarization boundaries may vary; integrations
should preserve the words and distinguish the alternating voices when the selected model supports
the requested capabilities.

Regenerate it with `scripts/generate_test_fixture.sh` on a system with eSpeak NG and FFmpeg. The
fixture and its transcript are distributed under the repository's Apache-2.0 license.
