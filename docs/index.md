# OpenTranscribe MCP

**Own the recorder. Choose the intelligence.**

OpenTranscribe is a provider-independent MCP server for one bounded transformation:

```text
authorized audio + required capabilities + provider/model preference
-> normalized transcript
```

It does not discover recordings, identify real speakers, summarize meetings, write to downstream systems, or retain audio and transcripts by default.

Start with the [repository quickstart](https://github.com/fbossiere/open-transcribe-mcp#ten-minute-quickstart), then use these pages for architecture, provider capabilities, security, privacy, deployment, and operational detail.

If you are not a developer and want to transcribe a Plaud recorder on Ubuntu, follow the [step-by-step tutorial](tutorials/plaud-ubuntu.md) instead.

OpenTranscribe works only with audio the operator is authorized to process. It does not modify recorder firmware, extract credentials, or bypass access controls.
