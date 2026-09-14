# Desktop release acceptance

This sheet is the evidence record for the Debian desktop package. **Every scenario starts at
*Not tested*, and only a maintainer who has actually run it may change that.**

A passing automated test, a screenshot, a source reading, and a real user run are four different
kinds of evidence and are recorded as four different things. In particular, a green CI run is
*not* a scenario-level pass: it says the automated portion held on a runner, not that the package
installed and worked on a real desktop.

## How to record a run

For each real run, record: the **source revision**, the **package digest** (`sha256sum` of the
`.deb`), the **OS and architecture**, the **session type** (Wayland or X11), the **client and its
version**, the **date**, and the **result**. Put it in the Evidence column as a short line, for
example:

```
2026-10-02 · 60e045f · sha256:3f9c… · Ubuntu 24.04 amd64 · wayland · Claude Desktop 1.4.2 · pass
```

## Evidence categories

| Mark | Meaning |
|---|---|
| `auto` | An automated test in this repository covers it. Names the test. |
| `source` | Established by reading the source. Weakest category; never sufficient alone for a release gate. |
| `shot` | A screenshot or recording exists. |
| `run` | A maintainer performed the scenario end to end on a real system. |

## Packaging

| ID | Scenario | Required result | Status | Evidence |
|---|---|---|---|---|
| PKG-01 | Graphical installation on a clean supported system without Python or `uv` | OS installer succeeds; Setup appears in the menu and opens without a terminal | Not tested | — |
| PKG-02 | Install, upgrade, and remove with no graphical session | Package operations complete without discovering users or contacting external services | Not tested | `auto` partial: `tests/desktop/test_packaging_contracts.py::test_maintainer_scripts_do_nothing_per_user_and_reach_no_network` |
| PKG-03 | Existing CLI installation | Existing commands and configuration retain their original behaviour | Not tested | `auto` partial: `tests/desktop/test_diagnostics_and_cli.py::test_the_bare_entry_point_still_starts_http` |
| PKG-04 | Final archive inspection and isolated engine launch | Correct executables, dependencies, metadata, licences, and engine version are present | Not tested | `auto` partial: `scripts/verify_deb.py` runs in the release workflow |
| PKG-05 | Package install with application networking denied | No installer or build-tool downloads; local setup opens; online steps report unavailable | Not tested | `auto` partial: `tests/desktop/test_diagnostics_and_cli.py::test_the_engine_runs_without_the_project_checkout_on_the_path` |
| PKG-06 | Upgrade and downgrade, including a running client | No implicit data loss; incompatible schema and restart requirements are explicit | Not tested | `auto` partial: `tests/desktop/test_managed_config.py::test_a_newer_schema_is_refused_without_mutation` |

## Security and privacy

| ID | Scenario | Required result | Status | Evidence |
|---|---|---|---|---|
| SEC-01 | Missing, locked, or cancelled keyring | No plaintext or environment fallback, and no false setup success | Not tested | `auto`: `tests/desktop/test_credentials_and_runtime.py` |
| SEC-02 | Malicious `.env`, `OT_*`, or shadow executable on `PATH` | Managed engine uses explicit settings and the packaged binary | Not tested | `auto`: `test_managed_mode_ignores_ambient_environment`, `test_a_dotenv_in_the_working_directory_is_ignored` |
| SEC-03 | Symlink, bad permissions, malformed or future schema, concurrent writer | Fail safely or serialize correctly; preserve the last valid configuration | Not tested | `auto`: `tests/desktop/test_managed_config.py` |
| SEC-04 | Local STDIO startup and protocol activity | No listening socket; only valid MCP output on stdout; HTTP auth still enforced | Not tested | `auto`: `tests/desktop/test_stdio_transport.py` |
| SEC-05 | SSRF, redirects, unsafe endpoint, and credential-bearing errors | Rejection happens at the right boundary; secrets do not leak | Not tested | `auto` partial: `tests/unit/test_security.py`, `tests/unit/test_url_fuzz.py`, `tests/desktop/test_provider_setup.py` |
| SEC-06 | Provider disabled, or cross-provider fallback off | Neither explicit requests nor transient failures disclose audio to an unauthorized provider | Not tested | `auto`: `tests/desktop/test_policy.py` |
| SEC-07 | Temporary processing denied | A relay-only request fails before download and provider submission; no hidden disk fallback | Not tested | `auto`: `test_relay_is_refused_before_the_download` |
| SEC-08 | Temporary processing allowed, then success, failure, cancel, crash | Ownership, bounds, normal cleanup, expiry, and next-session recovery meet the lifecycle | Not tested | `auto`: `tests/desktop/test_temporary_audio.py` |
| SEC-09 | Diagnostic export and hostile sample or client output | Only allowlisted support data is exported; nothing executes or renders as active content | Not tested | `auto`: `test_the_export_carries_only_allowlisted_fields` |

## Configuration

| ID | Scenario | Required result | Status | Evidence |
|---|---|---|---|---|
| CFG-01 | Add and replace a provider key | New setup works; a failed replacement preserves the previous working configuration | Not tested | `auto`: `tests/desktop/test_setup_transaction.py` |
| CFG-02 | Multiple providers and incompatible capabilities | Canonical metadata drives selection; no silent downgrade or unauthorized fallback | Not tested | `auto` partial: `tests/unit/test_routing.py`, `tests/desktop/test_policy.py` |
| CFG-03 | Missing duration, stale or unknown pricing, retry and fallback | No misleading hard-budget guarantee; estimates and limits are labelled accurately | Not tested | `auto` partial: `tests/desktop/test_sample.py`, `test_the_cost_control_is_never_labelled_a_spending_cap` |

## Client integration

| ID | Scenario | Required result | Status | Evidence |
|---|---|---|---|---|
| CLI-01 | Supported real client | Registration readback succeeds and the client launches the exact bundled engine | Not tested | — |
| CLI-02 | Shared client store | One managed connection is created, without duplicate servers | Not tested | `auto` partial: `test_re_running_creates_no_second_server` |
| CLI-03 | Unsupported or missing client, or missing removal API | A precise manual path, or the operation is blocked; no blind config rewrite | Not tested | `auto` partial: `test_an_unreadable_client_configuration_is_never_rewritten` |
| CLI-04 | Existing user-managed or project-managed registration | Conflict or explicit takeover is shown; unrelated registrations survive | Not tested | `auto` partial: `test_a_user_managed_entry_is_a_conflict_not_a_target` |
| CLI-05 | Crash or cancellation after each mutation phase | Rerun reconciles partial state and safely resumes or compensates | Not tested | `auto` partial: `test_a_rerun_after_a_client_failure_reconciles` |
| CLI-06 | Client rejects disconnection | Recovery journal and needed local state remain; failure is visible and retryable | Not tested | `auto` partial: `test_a_client_refusal_keeps_the_saved_setup` |

## Use and interface

| ID | Scenario | Required result | Status | Evidence |
|---|---|---|---|---|
| USE-01 | Engine handshake only | The packaged engine answers MCP initialization and lists exactly the five tools | Not tested | `auto`: `test_the_packaged_engine_answers_with_exactly_the_expected_tools` |
| USE-02 | Optional public sample with a real provider key | A canonical transcript returns; cost and pricing date were shown first | Not tested | — |
| USE-03 | First run to a working assistant, by a person who did not build it | Setup completes without documentation, a terminal, or a maintainer's help | Not tested | — |
| USE-04 | Wayland and X11, 1280 × 720, 100% and 200% scaling, larger system fonts | No clipped buttons, no horizontal form scrolling, navigation stays visible | Not tested | — |
| USE-05 | Keyboard only, with a real Linux screen reader | Every action reachable, focus visible, labels and status changes announced | Not tested | — |
| USE-06 | French session locale, and the explicit language override | Both languages are complete, and no string is assembled by concatenation | Not tested | `auto` partial: `tests/desktop/test_interface_contracts.py` |
| USE-07 | Light and dark system themes | Contrast meets WCAG 2.2 AA; no status is carried by colour alone | Not tested | — |

## Client compatibility matrix

`config/desktop/clients.toml` carries a `support_status` per client. It is the release gate for
what the interface may offer as automatic setup:

| Status | What it means | How it is earned |
|---|---|---|
| `tested` | Registration and readback verified for this client version | A recorded CLI-01 run in this sheet |
| `untested` | The format is documented, but this build has not been tested against it | Default for every new entry |
| `manual_only` | There is no supported registration API | Design decision for that client |

**Every shipped entry is currently `untested`.** No entry may be promoted to `tested` without a
CLI-01 row above naming the client version and the date.

## Known gaps in this release

These are stated so they are not mistaken for tested behaviour:

- The packaging toolchain has been exercised end to end on **Debian 12**, not on the supported
  target: both bundles freeze, the payload passes `scripts/check_deb_payload.py`, `dpkg-deb`
  produces an archive, `scripts/verify_deb.py` accepts it, the extracted engine answers MCP with
  its five tools from an isolated environment, and the extracted assistant reaches its event
  loop. **No `.deb` has been installed on Ubuntu 24.04**, so PKG-01 and PKG-02 remain untested.
- No client has a recorded CLI-01 run, so the interface presents automatic registration as
  untested for every client and always verifies by reading the registration back.
- The engine handshake check bounds the tool-listing payload and the whole operation, and
  discards the engine's stderr. It does not additionally meter the raw protocol byte stream.
- Bit-for-bit reproducibility is **not** claimed. The build records its inputs and timestamps,
  but no independent rebuild has demonstrated an identical artifact.
- The licence and notice review for the exact bundled Python and Qt components is generated by
  `scripts/generate_notices.py` and must still be reviewed by a person before a release.
