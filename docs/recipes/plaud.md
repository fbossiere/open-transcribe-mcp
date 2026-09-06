# Plaud recipe

Plaud is an acquisition example, not a core dependency.

1. Use an authorized Plaud export, CLI, connector, or MCP integration to list recordings and obtain an original-audio URL.
2. Pass that temporary HTTPS URL to `transcribe_audio`.
3. Consume the canonical result, not Plaud- or provider-specific fields.
4. If stored mode was used, read all chunks and call `delete_transcript`.

```json
{
  "request": {
    "source": {"type": "url", "url": "https://AUTHORIZED-TEMPORARY-URL"},
    "provider": "auto",
    "routing_policy": "quality",
    "diarization": true,
    "timestamps": "segment",
    "transcript_style": "clean",
    "source_delivery": "auto",
    "result_mode": "auto"
  }
}
```

Vendor connector fields and URL lifetimes can change and are outside the OpenTranscribe compatibility contract. Do not extract credentials, reverse engineer protected systems, bypass access controls, or use audio without the necessary rights.

Plaud is a trademark of its respective owner. OpenTranscribe is independent and is not affiliated with, endorsed by, or sponsored by Plaud.
