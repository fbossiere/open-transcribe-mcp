#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$root_dir/tests/fixtures/open-transcribe-bilingual.wav"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

command -v espeak-ng >/dev/null
command -v ffmpeg >/dev/null

espeak-ng -v en-us+f3 -s 145 -w "$work_dir/en-1.wav" -- \
  "Hello. This is the OpenTranscribe synthetic test recording."
espeak-ng -v fr+m3 -s 145 -w "$work_dir/fr-1.wav" -- \
  "Bonjour. Ceci est l'enregistrement de test synthétique d'OpenTranscribe."
espeak-ng -v en-us+f3 -s 145 -w "$work_dir/en-2.wav" -- \
  "A good recorder should not lock its owner into one transcription model."
espeak-ng -v fr+m3 -s 145 -w "$work_dir/fr-2.wav" -- \
  "Un bon enregistreur doit laisser son propriétaire choisir son modèle de transcription."

ffmpeg -hide_banner -loglevel error -y \
  -i "$work_dir/en-1.wav" \
  -f lavfi -t 0.7 -i anullsrc=r=22050:cl=mono \
  -i "$work_dir/fr-1.wav" \
  -f lavfi -t 0.7 -i anullsrc=r=22050:cl=mono \
  -i "$work_dir/en-2.wav" \
  -f lavfi -t 0.7 -i anullsrc=r=22050:cl=mono \
  -i "$work_dir/fr-2.wav" \
  -filter_complex "[0:a][1:a][2:a][3:a][4:a][5:a][6:a]concat=n=7:v=0:a=1[out]" \
  -map "[out]" -ar 22050 -ac 1 -c:a pcm_s16le "$output"
