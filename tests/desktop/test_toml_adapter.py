"""CLI-02 through CLI-04 for the TOML store the ChatGPT app and Codex share.

The file this adapter edits is one the user also writes by hand, so the tests below are mostly
about what it leaves alone: their comments, their other servers, and their formatting.
"""

import tomllib
from pathlib import Path

import pytest

from open_transcribe.desktop.clients.base import ServerRegistration
from open_transcribe.desktop.clients.toml_store import TomlMcpServersAdapter
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

ENGINE = Path("/opt/open-transcribe-assistant/open-transcribe-mcp")
CONFIG = Path("/home/user/.config/open-transcribe-mcp/desktop/config.toml")

EXISTING = """\
# My own Codex settings. Please keep these.
model = "gpt-5-codex"

[mcp_servers.notes]
command = "/usr/bin/notes"
args = ["--serve"]

[tools]
web_search = true
"""


@pytest.fixture
def registration() -> ServerRegistration:
    return ServerRegistration(name="open-transcribe", command=ENGINE, config_path=CONFIG)


@pytest.fixture
def client_config(tmp_path: Path) -> Path:
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(EXISTING, encoding="utf-8")
    return path


@pytest.fixture
def adapter(client_config: Path) -> TomlMcpServersAdapter:
    return TomlMcpServersAdapter(
        adapter_id="chatgpt-app", display_name="ChatGPT app", config_path=client_config
    )


def test_registering_preserves_the_comments_and_every_other_table(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    text = client_config.read_text(encoding="utf-8")
    assert "# My own Codex settings. Please keep these." in text
    assert text.startswith('# My own Codex settings. Please keep these.\nmodel = "gpt-5-codex"\n')
    assert "[tools]\nweb_search = true\n" in text

    document = tomllib.loads(text)
    assert document["model"] == "gpt-5-codex"
    assert document["tools"] == {"web_search": True}
    assert document["mcp_servers"]["notes"] == {"command": "/usr/bin/notes", "args": ["--serve"]}
    registered = document["mcp_servers"]["open-transcribe"]
    assert registered["command"] == str(ENGINE)
    assert registered["args"] == list(registration.args)


def test_registering_into_a_file_that_does_not_exist_yet(
    tmp_path: Path, registration: ServerRegistration
) -> None:
    path = tmp_path / ".codex" / "config.toml"
    adapter = TomlMcpServersAdapter(
        adapter_id="chatgpt-app", display_name="ChatGPT app", config_path=path
    )
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    assert document["mcp_servers"]["open-transcribe"]["command"] == str(ENGINE)


def test_readback_confirms_the_registration(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration
) -> None:
    assert adapter.readback("open-transcribe") is None
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    entry = adapter.readback("open-transcribe")
    assert entry is not None
    assert entry.fingerprint() == registration.fingerprint()


def test_re_running_creates_no_second_server(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    again = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert again.changes_nothing
    adapter.apply(again)
    assert client_config.read_text(encoding="utf-8").count("[mcp_servers.open-transcribe]") == 1


def test_a_user_managed_entry_is_a_conflict_not_a_target(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    client_config.write_text(
        EXISTING + '\n[mcp_servers.open-transcribe]\ncommand = "/usr/bin/theirs"\n',
        encoding="utf-8",
    )
    plan = adapter.plan(registration, owned=frozenset(), takeover=False)
    assert plan.blocked
    with pytest.raises(DesktopError) as error:
        adapter.apply(plan)
    assert error.value.code is DesktopErrorCode.CLIENT_CONFLICT
    assert "/usr/bin/theirs" in client_config.read_text(encoding="utf-8")


def test_takeover_is_explicit_and_replaces_only_the_named_entry(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    client_config.write_text(
        EXISTING + '\n[mcp_servers.open-transcribe]\ncommand = "/usr/bin/theirs"\n',
        encoding="utf-8",
    )
    plan = adapter.plan(registration, owned=frozenset(), takeover=True)
    assert not plan.blocked
    adapter.apply(plan)
    document = tomllib.loads(client_config.read_text(encoding="utf-8"))
    assert document["mcp_servers"]["open-transcribe"]["command"] == str(ENGINE)
    assert document["mcp_servers"]["notes"]["command"] == "/usr/bin/notes"


def test_removal_takes_only_the_named_entry(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    assert adapter.remove("open-transcribe") is True
    document = tomllib.loads(client_config.read_text(encoding="utf-8"))
    assert "open-transcribe" not in document["mcp_servers"]
    assert document["mcp_servers"]["notes"]["command"] == "/usr/bin/notes"
    assert document["model"] == "gpt-5-codex"
    assert adapter.remove("open-transcribe") is False


def test_an_unparsable_configuration_is_never_rewritten(
    adapter: TomlMcpServersAdapter, registration: ServerRegistration, client_config: Path
) -> None:
    client_config.write_text("this is not = = toml\n", encoding="utf-8")
    with pytest.raises(DesktopError) as error:
        adapter.apply(adapter.plan(registration, owned=frozenset(), takeover=False))
    assert error.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED
    assert client_config.read_text(encoding="utf-8") == "this is not = = toml\n"


def test_a_symlinked_configuration_is_refused(
    tmp_path: Path, registration: ServerRegistration
) -> None:
    target = tmp_path / "real.toml"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "config.toml"
    link.symlink_to(target)
    adapter = TomlMcpServersAdapter(
        adapter_id="chatgpt-app", display_name="ChatGPT app", config_path=link
    )
    with pytest.raises(DesktopError) as error:
        adapter.inventory()
    assert error.value.code is DesktopErrorCode.CLIENT_UNSUPPORTED


def test_the_matrix_offers_the_chatgpt_app_where_its_store_exists(tmp_path: Path) -> None:
    from open_transcribe.desktop.clients.registry import build_adapters

    config_dir = Path("config")
    environment = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "config")}
    assert not any(a.adapter_id == "chatgpt-app" for a in build_adapters(config_dir, environment))

    (tmp_path / ".codex").mkdir()
    adapters = build_adapters(config_dir, environment)
    chatgpt = next(a for a in adapters if a.adapter_id == "chatgpt-app")
    assert chatgpt.display_name == "ChatGPT app"
    assert chatgpt.config_path == tmp_path / ".codex" / "config.toml"  # type: ignore[attr-defined]
