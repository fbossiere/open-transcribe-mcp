"""CLI-02, CLI-03 and CLI-04: registration, conflicts, takeover, and the manual path."""

import json
from pathlib import Path

import pytest

from open_transcribe.desktop.clients.base import Ownership, ServerRegistration, SupportStatus
from open_transcribe.desktop.clients.json_store import JsonMcpServersAdapter
from open_transcribe.desktop.clients.manual import ManualRegistrationAdapter
from open_transcribe.desktop.clients.registry import build_adapters
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

ENGINE = Path("/opt/open-transcribe-assistant/open-transcribe-mcp")
CONFIG = Path("/home/user/.config/open-transcribe-mcp/desktop/config.toml")


@pytest.fixture
def registration() -> ServerRegistration:
    return ServerRegistration(name="open-transcribe", command=ENGINE, config_path=CONFIG)


@pytest.fixture
def client_config(tmp_path: Path) -> Path:
    path = tmp_path / "client" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"theme": "dark", "mcpServers": {"notes": {"command": "/usr/bin/notes"}}}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def adapter(client_config: Path) -> JsonMcpServersAdapter:
    return JsonMcpServersAdapter(
        adapter_id="demo", display_name="Demo client", config_path=client_config
    )


def test_a_registration_must_use_absolute_paths() -> None:
    with pytest.raises(ValueError, match="absolute"):
        ServerRegistration(name="x", command=Path("open-transcribe-mcp"), config_path=CONFIG)


def test_a_registration_carries_no_secret(registration: ServerRegistration) -> None:
    rendered = json.dumps(registration.as_fields())
    assert "key" not in rendered.lower()
    assert registration.args == ("serve", "--transport", "stdio", "--config", str(CONFIG))


def test_registering_preserves_every_unrelated_entry(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    document = json.loads(client_config.read_text(encoding="utf-8"))
    assert document["theme"] == "dark"
    assert document["mcpServers"]["notes"] == {"command": "/usr/bin/notes"}
    assert document["mcpServers"]["open-transcribe"]["command"] == str(ENGINE)


def test_readback_confirms_the_registration(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    entry = adapter.readback("open-transcribe")
    assert entry is not None
    assert entry.fingerprint() == registration.fingerprint()


def test_re_running_creates_no_second_server(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    """CLI-02: one managed connection, never a duplicate beside it."""
    for _ in range(3):
        plan = adapter.plan(registration, owned=frozenset(), takeover=False)
        adapter.apply(plan)
    document = json.loads(client_config.read_text(encoding="utf-8"))
    assert sorted(document["mcpServers"]) == ["notes", "open-transcribe"]


def test_a_user_managed_entry_is_a_conflict_not_a_target(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    """CLI-04: an entry this installation did not create is never overwritten."""
    client_config.write_text(
        json.dumps(
            {"mcpServers": {"open-transcribe": {"command": "/usr/local/bin/uv", "args": ["run"]}}}
        ),
        encoding="utf-8",
    )
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert plan.blocked
    assert plan.conflicts[0].command == "/usr/local/bin/uv"
    with pytest.raises(DesktopError) as caught:
        adapter.apply(plan)
    assert caught.value.code is DesktopErrorCode.CLIENT_CONFLICT
    document = json.loads(client_config.read_text(encoding="utf-8"))
    assert document["mcpServers"]["open-transcribe"]["command"] == "/usr/local/bin/uv"


def test_takeover_is_explicit_and_replaces_only_the_named_entry(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    client_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "open-transcribe": {"command": "/usr/local/bin/uv", "args": ["run"]},
                    "notes": {"command": "/usr/bin/notes"},
                }
            }
        ),
        encoding="utf-8",
    )
    plan = adapter.plan(registration, owned=frozenset(), takeover=True)
    assert not plan.blocked
    assert plan.takeover[0].command == "/usr/local/bin/uv"
    adapter.apply(plan)
    document = json.loads(client_config.read_text(encoding="utf-8"))
    assert document["mcpServers"]["open-transcribe"]["command"] == str(ENGINE)
    assert document["mcpServers"]["notes"] == {"command": "/usr/bin/notes"}


def test_a_previously_recorded_registration_is_recognized_as_ours(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    """Ownership comes from records and observed launch details, not from a display name."""
    client_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "open-transcribe": {
                        "command": "/opt/open-transcribe-assistant/open-transcribe-mcp",
                        "args": ["serve", "--transport", "stdio", "--config", "/old/config.toml"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    entry = adapter.inventory()[0]
    assert entry.fingerprint() is not None
    plan = adapter.plan(registration, owned=frozenset({entry.fingerprint() or ""}), takeover=False)
    assert not plan.blocked
    assert plan.actions[0].kind == "update_server"


def test_an_unreadable_client_configuration_is_never_rewritten(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    """CLI-03: no blind rewrite. The user gets a precise manual path instead."""
    client_config.write_text("this is not json", encoding="utf-8")
    with pytest.raises(DesktopError) as caught:
        adapter.plan(registration, owned=frozenset(), takeover=False)
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED
    assert client_config.read_text(encoding="utf-8") == "this is not json"


def test_a_symlinked_client_configuration_is_refused(
    tmp_path: Path, registration: ServerRegistration
) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "config.json"
    link.symlink_to(real)
    adapter = JsonMcpServersAdapter(adapter_id="d", display_name="D", config_path=link)
    with pytest.raises(DesktopError) as caught:
        adapter.inventory()
    assert caught.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED


def test_removal_takes_only_the_named_entry(
    adapter: JsonMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    assert adapter.remove("open-transcribe") is True
    assert adapter.remove("open-transcribe") is False
    document = json.loads(client_config.read_text(encoding="utf-8"))
    assert sorted(document["mcpServers"]) == ["notes"]


def test_the_manual_adapter_changes_nothing(registration: ServerRegistration) -> None:
    adapter = ManualRegistrationAdapter()
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert plan.changes_nothing
    assert adapter.support_status is SupportStatus.MANUAL_ONLY
    adapter.apply(plan)
    assert adapter.readback("open-transcribe") is None


def test_the_packaged_matrix_claims_no_tested_support_yet() -> None:
    """Nothing may be promoted to `tested` without a recorded acceptance run."""
    adapters = build_adapters(Path("config"), {"HOME": "/home/nobody"})
    assert adapters[-1].adapter_id == "manual"
    assert all(
        adapter.support_status is not SupportStatus.TESTED
        for adapter in adapters
        if adapter.adapter_id != "manual"
    )


def test_discovery_is_limited_to_the_locations_the_matrix_names(tmp_path: Path) -> None:
    adapters = build_adapters(Path("config"), {"HOME": str(tmp_path)})
    assert [adapter.adapter_id for adapter in adapters] == ["manual"]


def test_classification_never_trusts_a_name_alone(registration: ServerRegistration) -> None:
    from open_transcribe.desktop.clients.base import ExistingEntry, classify

    impostor = ExistingEntry(name="open-transcribe", command="/opt/evil/engine", args=())
    assert classify(impostor, registration, frozenset()) is Ownership.FOREIGN
    nameless = ExistingEntry(name="open-transcribe")
    assert classify(nameless, registration, frozenset()) is Ownership.UNKNOWN
