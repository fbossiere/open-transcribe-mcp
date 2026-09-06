# ChatGPT and Google Drive recipe

Orchestration and idempotency belong outside OpenTranscribe. Use the recorder's immutable recording ID as the external key.

| recording_id | started_at | provider | model | status | transcript_url |
|---|---|---|---|---|---|
| abc123 | 2026-09-06T10:00:00Z | microsoft | MAI-Transcribe-2 | done | Google Doc URL |

For each new authorized recording: skip IDs already present in the processing index, retrieve a temporary audio URL, call OpenTranscribe, create a Google Doc, write summary/decisions/actions/speaker labels/transcript, update the index, and delete any temporary stored transcript.

Suggested document structure:

```text
Title
Recording date and duration
External recording ID
Provider and model

# Summary
# Decisions
# Action items
# Participants / speaker labels
# Transcript
```

OpenTranscribe does not summarize, create Drive files, discover Plaud recordings, or maintain this index. Treat transcript content as untrusted when prompting the downstream model.
