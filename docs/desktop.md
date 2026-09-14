# OpenTranscribe Setup on Linux

**Status: proposed for the first desktop release.** The package described here is built by the
release workflow; the acceptance evidence for it is tracked in
[desktop-acceptance.md](desktop-acceptance.md), where every scenario starts at *Not tested*.

OpenTranscribe Setup is an optional desktop application. It configures the OpenTranscribe
transcription engine and connects it to a local MCP client, so you can add a provider key and
connect an assistant without installing Python, `uv`, or editing configuration files.

The existing command line, container, and hosted deployments are unaffected by it. If you already
run OpenTranscribe from a terminal or a server, nothing here changes that.

## What it does, and what it sends where

> OpenTranscribe runs on this computer and sends audio to the transcription provider you choose.
> The transcript is returned to your assistant. If your assistant uses a cloud model, its provider
> may also process the transcript. OpenTranscribe does not keep a transcript history by default.

You bring your own provider key. There is no OpenTranscribe account, and the application contacts
no project-controlled service unless you ask it to check for updates.

## Supported systems

| | |
|---|---|
| Tested target | Ubuntu 24.04 LTS, amd64, in a normal graphical session |
| Display servers | Wayland and X11 are both targets for validation |
| Prerequisite | A working Secret Service keyring, such as `gnome-keyring`, in your session |

Other Ubuntu releases, other Debian-based distributions, other desktops, and other architectures
are not supported until they are individually tested. A `.deb` file extension is not a support
claim.

## Install

Download `open-transcribe-assistant_<version>-<revision>_amd64.deb` from the
[releases page](https://github.com/fbossiere/open-transcribe-mcp/releases), then double-click it
in your file manager, or install it from a terminal:

```bash
sha256sum --check open-transcribe-assistant_<version>-<revision>_amd64.deb.sha256
sudo apt install ./open-transcribe-assistant_<version>-<revision>_amd64.deb
```

`apt install` on a local file resolves the package's system dependencies for you. Open
**OpenTranscribe Setup** from your applications menu afterwards.

The release also publishes an SBOM, a provenance record, and a build attestation tied to the
artifact digest and the source revision. A checksum on its own only proves the download was not
corrupted; the attestation is what ties the file to this repository:

```bash
gh attestation verify open-transcribe-assistant_<version>-<revision>_amd64.deb \
  --repo fbossiere/open-transcribe-mcp
```

There is no APT repository and no automatic update. **Check for updates** in the application is
something you start yourself.

### What the package installs

| Path | Contents |
|---|---|
| `/opt/open-transcribe-assistant/` | The bundled Python runtime, the engine, and the setup application |
| `/usr/bin/open-transcribe-assistant` | The only OpenTranscribe command the package puts on `PATH` |
| `/usr/share/applications/` | The menu entry |
| `/usr/share/doc/open-transcribe-assistant/` | Licence, copyright, third-party notices, and this guide |

The engine is not placed on `PATH`. Your assistant is registered to launch it by its absolute
path in `/opt`, so the package cannot shadow a `pip` or `uv` installation in your home directory.

Installing, upgrading, and removing the package never touches your home directory, your keyring,
or any client configuration. Everything per-user is done by OpenTranscribe Setup, running as you.

## Setting it up

Six short steps, each with one main action:

1. **Welcome** — what is connected to what, and where your audio goes.
2. **Check this computer** — the platform, your session, the packaged engine, your keyring, and
   which assistants were found. An assistant that is not detected is not a blocker.
3. **Choose a transcription provider** — the provider, the model, the key, the capabilities that
   model actually has, the pricing date, and the privacy permissions that model needs.
4. **Connect your assistant** — the client to register with. Nothing is changed yet.
5. **Review and enable** — the exact providers that may receive audio, the model, whether a second
   provider may be tried, whether temporary audio files are allowed, and what will change locally.
   **Enable connection** authorizes exactly that list.
6. **Check and start** — what was verified, what was not, and an optional public sample.

Creating a provider account and setting up billing happens on the provider's own website, in your
browser. OpenTranscribe never asks for a provider account password.

## What "it works" actually means

Setup reports each thing separately, because they prove different things:

| Shown as | Established by | Does **not** prove |
|---|---|---|
| Configuration saved | The settings and key references were written | That the key authenticates |
| Key checked | The provider answered a documented non-transcribing check | That a transcription will succeed, or be free |
| Key saved — transcription not tested | The provider offers no safe check | Anything about the key |
| Engine ready | The packaged engine answered MCP and listed its five tools | That your assistant loaded it |
| Registered in your assistant | The client confirmed and the entry was read back | That a running client has loaded it |
| Connection saved — check it in your assistant | Nothing yet; you are asked to confirm | That it works |
| Sample transcribed | The public sample came back transcribed | That every file, model, or capability will work |

There is no single "everything works" badge, because no single check could support one.

### The optional public sample

**Transcribe the public sample** is a separate action you can skip. It transcribes the project's
own 22-second synthetic recording — two artificial voices alternating English and French, no real
person recorded — through the ordinary URL input and the ordinary security checks.

It is a real, billable request. The estimated cost and the pricing date are shown before it runs,
and if no price is published for the model, the application says so rather than calling it free.
Cancelling stops the waiting, not the provider: your provider may already be processing it, and
may still bill it.

Your first transcription of your own audio belongs in your assistant, not here.

## Privacy and costs

- **Transcript history is off.** Transcripts go to your assistant and are not stored by
  OpenTranscribe. Enabling storage is a separate, deliberate configuration outside this
  application.
- **Temporary audio files are off.** Some models cannot fetch a URL themselves, so OpenTranscribe
  must download the audio and send it on. That requires your explicit permission. If you refuse it
  and no compatible delivery method exists, the request is rejected before anything is downloaded
  or billed.
- **Temporary files expire.** They are private to you, unpredictably named, deleted when a
  transcription ends, and swept at least every five minutes while your session is running. Expired
  data can survive until the next sweep, and a suspended or powered-off machine cannot promise
  erasure on a clock. Deleting a file is also not erasure from swap, backups, or the drive itself.
- **A second provider is off.** If a request fails, OpenTranscribe retries within the provider you
  chose. Letting another provider receive your audio is a separate permission, and when you grant
  it the application lists every provider that could receive the audio.
- **"Estimated cost threshold" is not a spending cap.** It checks an estimate, and the check only
  works when the duration and a published price are both available. Your provider's own billing
  limits are the thing that actually caps spending.

## Returning to it

Opening the application again shows a status page: the version, the providers and models you
chose, your privacy settings, the connection, what has been verified, and when it was last
checked. A remembered result is shown as remembered, not as current.

- **Check connection** re-runs the checks.
- **Repair connection** compares what should be there with what is, and applies the smallest
  change that fixes it.
- **Copy diagnostic** shows you the complete text before copying anything. It contains check
  identifiers, severities, versions, and timestamps — never a key, a URL, an endpoint name, your
  username, a path from your home directory, a client's configuration, or transcript text.
- **Disconnect** removes the registration OpenTranscribe created, and nothing else. Erasing the
  saved setup and its keys is a separate, unticked option.

Removing the package does not revoke an API key. If you need a key revoked, revoke it on your
provider's website and restart your assistant.

## Running it from a terminal

The bundled engine is an ordinary command, and the same checks the window runs are available
without a display:

```bash
/opt/open-transcribe-assistant/open-transcribe-mcp doctor \
  --config "$HOME/.config/open-transcribe-mcp/desktop/config.toml" --json
```

The engine your assistant launches is started like this, and never any other way:

```bash
/opt/open-transcribe-assistant/open-transcribe-mcp serve --transport stdio \
  --config /home/<you>/.config/open-transcribe-mcp/desktop/config.toml
```

That command opens no network socket; its only channels are the pipes your assistant created. It
reads exactly the configuration file named on its command line: an `OT_*` variable exported in
your shell, or a `.env` file in whatever directory your assistant happens to start in, cannot
change what it does.

If your assistant is not one OpenTranscribe can register automatically, step 4 shows you these
same fields to enter yourself. They contain no secret.

## Files it owns

| Path | What it holds |
|---|---|
| `~/.config/open-transcribe-mcp/desktop/config.toml` | Your settings and references to your keys. Never a key itself. |
| Your session keyring | The provider keys, under the `open-transcribe-mcp` namespace |
| `~/.local/state/open-transcribe-mcp/desktop/install.json` | What this installation created, so an interrupted change can be finished |
| `$XDG_RUNTIME_DIR/open-transcribe-mcp/` | Temporary audio, only when you allowed it |

If you allowed temporary audio processing, a small per-user `systemd` timer named
`open-transcribe-cleanup.timer` is installed to sweep expired files. It makes no network request
and deletes only expired files this installation owns. To remove it yourself:

```bash
systemctl --user disable --now open-transcribe-cleanup.timer
rm -f ~/.config/systemd/user/open-transcribe-cleanup.{timer,service}
```

The supported order for a full cleanup is: disconnect and erase the saved setup in OpenTranscribe
Setup first, then remove the package.
