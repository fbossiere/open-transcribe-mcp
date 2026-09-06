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

The default request asks for diarization and clean output. It will not route to Groq under strict capability negotiation. To use Groq explicitly, set `diarization=false` and `transcript_style=verbatim`.

Pricing metadata lives in `config/pricing.yaml`. It is informational and deliberately separate from adapter code. Expired or unavailable metadata produces warnings.
