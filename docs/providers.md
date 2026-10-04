# Providers and capabilities

Capabilities are versioned metadata, not promises of parity. `list_transcription_models` is the runtime source of truth for the deployed version.

| Model | URL input | Diarization | Timestamps | Styles | Hints |
|---|---:|---:|---|---|---:|
| Microsoft MAI-Transcribe-2 | Yes | Yes | none, segment, word | clean, verbatim | Yes |
| ElevenLabs Scribe v2 | Yes | Yes | none, segment, word | clean, verbatim | Yes |
| Groq Whisper large v3 | Yes | No | none, segment, word | verbatim | prompt |
| Groq Whisper large v3 turbo | Yes | No | none, segment, word | verbatim | prompt |

Microsoft requires a Speech resource endpoint and key. OpenTranscribe calls the synchronous Fast Transcription REST endpoint with enhanced mode. ElevenLabs calls `/v1/speech-to-text` with zero retention enabled by default. That provider option requires an eligible account; operators who deliberately accept provider-side logging may set `OT_ELEVENLABS__ZERO_RETENTION=false`. Groq uses the OpenAI-compatible audio transcription endpoint and supports either URL passthrough or an explicitly requested proxy upload.

Groq word timestamps are requested together with segment timestamps so word data remains attached to canonical segments instead of producing a structurally incomplete response.

`diarization`, `timestamps`, and `transcript_style` are unset by default, which asks for no particular capability: a request naming only its audio source routes to Groq as readily as to Microsoft, and the response metadata reports what the selected model actually applied. State a capability to require it, and no model lacking it is selected: `diarization=true` excludes both Groq models, as does `transcript_style=clean`. Adding `strict_capabilities=false` downgrades instead of failing, with a `requested_capability_not_supported:*` warning naming what was dropped.

Pricing metadata lives in `config/pricing.yaml`. It is informational and deliberately separate from adapter code. Expired or unavailable metadata produces warnings.

## French conversations with speaker turns

ElevenLabs Scribe v2 is an available option for French audio with speaker diarization. Its [transcription documentation](https://elevenlabs.io/docs/overview/capabilities/speech-to-text) lists French and speaker diarization. Availability does not establish an accuracy advantage over Whisper on your recordings: compare the same authorized audio, transcription errors, speaker assignments, latency, and cost before making that claim.

Enable the adapter by supplying `OT_ELEVENLABS__API_KEY` through your deployment's secret configuration. Keep `OT_ELEVENLABS__ZERO_RETENTION=true`; the account must be eligible for this option. For the desktop assistant, enable ElevenLabs and store the key through Setup. Use `list_transcription_models(configured_only=true)` to verify the model is configured. This is not a live transcription or entitlement check.

Request the language and speaker separation explicitly:

```json
{
  "source": {"type": "url", "url": "https://example.com/authorized-recording.mp3"},
  "provider": "elevenlabs",
  "model": "scribe-v2",
  "routing_policy": "fixed",
  "language": "fr",
  "diarization": true,
  "timestamps": "segment",
  "transcript_style": "verbatim",
  "strict_capabilities": true,
  "allow_fallback": false,
  "result_mode": "auto"
}
```

The example URL is a placeholder. Supply your authorized HTTPS audio URL only to the tool, keeping signed URLs out of files and logs. If the number of speakers is known, optionally supply `speaker_count_hint`; otherwise let the model estimate it.

Render the canonical `segments` as timestamped speaker turns. Their `speaker` labels remain stable within a transcript, including when a speaker returns: `SPEAKER_01`, `SPEAKER_02`, then `SPEAKER_01` again. The flat `text` field does not preserve speaker turns. These labels distinguish voices; they do not identify people. Report missing speaker labels instead of inventing them. Transcription and diarization happen together from the audio; a flat transcript alone cannot recover acoustic speaker boundaries.

Both Groq Whisper models are incompatible with `diarization=true`. Strict routing rejects them before a provider call. Disabling strict capability checking would drop that requirement with a warning, so keep it enabled when speaker turns matter.
