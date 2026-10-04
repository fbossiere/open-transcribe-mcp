---
title: OpenTranscribe MCP
description: Keep your recorder. Choose your transcription model. Set up provider-independent speech-to-text on Linux or Scaleway.
hide:
  - navigation
  - toc
  - footer
---

<div class="ot-home" markdown="1">

<div class="ot-hero" markdown="1">
<div class="ot-intro" markdown="1">

<p class="ot-eyebrow"><span aria-hidden="true">●</span> OPEN SOURCE · SPEECH TO TEXT</p>

# Own the recorder.<br><span>Choose the intelligence.</span>

<p class="ot-lead">Your audio. Your model. One transcript.</p>

Keep the recorder you like. Send authorized audio to Microsoft, ElevenLabs or Groq, and get a
consistent transcript your MCP client can use anywhere.

<div class="ot-actions" markdown="1">

[Get started <span aria-hidden="true">↗</span>](#choose-your-setup){ .ot-button .ot-button--primary }
[Explore the providers <span aria-hidden="true">→</span>](providers.md){ .ot-button .ot-button--secondary }

</div>

<p class="ot-release"><span class="ot-release-dot" aria-hidden="true"></span> Stable v1.2.1 <span aria-hidden="true">/</span> Apache 2.0 <span aria-hidden="true">/</span> Self-hosted</p>

</div>

<div class="ot-flow" aria-label="Audio flows through OpenTranscribe to your selected provider and returns a normalized transcript">
  <div class="ot-flow-heading"><span>THE TRANSCRIPTION PIPELINE</span><span class="ot-flow-live">MCP</span></div>
  <div class="ot-audio">
    <div class="ot-flow-label"><span class="ot-step">01</span><span>Any authorized audio</span><span class="ot-file">HTTPS</span></div>
    <svg class="ot-wave" viewBox="0 0 320 64" role="img" aria-label="An audio waveform"><g stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M4 29v6m10-12v18m10-24v30m10-17v16m10-27v38m10-45v52m10-40v28m10-20v12m10-27v42m10-35v28m10-45v58m10-42v26m10-17v8m10-21v34m10-42v50m10-36v22m10-16v10m10-33v54m10-45v36m10-27v18m10-17v16m10-29v42m10-38v34m10-23v12m10-13v14m10-20v26m10-18v10m10-16v22m10-18v14m10-11v8m10-7v6m10-8v10"/></g></svg>
  </div>
  <div class="ot-flow-connector" aria-hidden="true">↓</div>
  <div class="ot-router"><span class="ot-step">02</span><span><strong>OpenTranscribe</strong><small>Check capabilities. Route audio.</small></span><span class="ot-router-icon" aria-hidden="true">↗</span></div>
  <div class="ot-flow-connector" aria-hidden="true">↓</div>
  <div class="ot-provider-options"><span>Microsoft<small>MAI</small></span><span class="ot-provider-selected">ElevenLabs<small>Scribe</small></span><span>Groq<small>Whisper</small></span></div>
  <div class="ot-flow-connector" aria-hidden="true">↓</div>
  <div class="ot-transcript"><div class="ot-flow-label"><span class="ot-step">03</span><span>One normalized transcript</span></div><div class="ot-transcript-line"><span>SPEAKER_01</span><i aria-hidden="true"></i><i aria-hidden="true"></i></div><div class="ot-transcript-line"><span>SPEAKER_02</span><i aria-hidden="true"></i><i aria-hidden="true"></i></div><p>Speaker turns when your model supports them.</p></div>
</div>
</div>

<div class="ot-principles">
  <div><span class="ot-principle-icon" aria-hidden="true">↔</span><span><strong>Provider independent</strong><small>Same contract. Different intelligence.</small></span></div>
  <div><span class="ot-principle-icon" aria-hidden="true">◈</span><span><strong>Explicit capabilities</strong><small>Require speaker turns. Never lose them silently.</small></span></div>
  <div><span class="ot-principle-icon" aria-hidden="true">◎</span><span><strong>Retention is your choice</strong><small>Optional storage. Clear provider policies.</small></span></div>
</div>

<div class="ot-section-intro" markdown="1">

<p class="ot-eyebrow">START HERE</p>

## Choose your setup

Use it locally, host it for your clients, or start with a recorder recipe.

</div>

<div class="ot-paths">

<a class="ot-path" href="configuration/">
<span class="ot-path-number">01 / CONFIGURE</span>
<h3>Connect your providers</h3>
<p>Choose Groq, ElevenLabs, Microsoft, or a combination. Understand defaults, authentication and retention.</p>
<span class="ot-path-link">Configuration guide <span aria-hidden="true">↗</span></span>
</a>

<a class="ot-path" href="desktop/">
<span class="ot-path-number">02 / LOCAL</span>
<h3>Start on Linux</h3>
<p>Install OpenTranscribe Setup, add your keys and connect a local MCP client. No Python setup needed.</p>
<span class="ot-path-link">Linux desktop guide <span aria-hidden="true">↗</span></span>
</a>

<a class="ot-path" href="deploy-scaleway/">
<span class="ot-path-number">03 / HOSTED</span>
<h3>Deploy on Scaleway</h3>
<p>Run a secure MCP endpoint with scale-to-zero. Follow the Terraform setup, then upgrade with verified images.</p>
<span class="ot-path-link">Deployment guide <span aria-hidden="true">↗</span></span>
</a>

</div>

<div class="ot-guides" markdown="1">

**Working with a Plaud recorder?** Start with the [Ubuntu walkthrough](tutorials/plaud-ubuntu.md).
Prefer Python or Docker? Use the [repository quickstart](https://github.com/fbossiere/open-transcribe-mcp#ten-minute-quickstart).

</div>

<div class="ot-bottom" markdown="1">
<div markdown="1">

<p class="ot-eyebrow">A SMALL, FOCUSED TOOL</p>

### Audio in. A portable transcript out.

OpenTranscribe handles transcription. Summaries, storage libraries and downstream workflows
belong to your MCP client. Use only audio you are authorized to process; speaker labels never
identify real people.

</div>
<div class="ot-more" markdown="1">

[Architecture →](architecture.md)

[Security and privacy →](security.md)

[Publication protocol →](releasing.md)

</div>
</div>
</div>
