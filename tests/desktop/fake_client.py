#!/usr/bin/env python3
"""A stand-in MCP client with a `mcp list|add|remove` command line, for adapter tests."""

import json
import os
import sys

store = os.environ["FAKE_CLIENT_STORE"]
argv = sys.argv[1:]


def load():
    with open(store, encoding="utf-8") as handle:
        return json.load(handle)


def save(document):
    with open(store, "w", encoding="utf-8") as handle:
        json.dump(document, handle)


if argv[:2] == ["mcp", "list"]:
    sys.stdout.write(json.dumps(load()))
elif argv[:2] == ["mcp", "add"]:
    name = argv[2]
    rest = argv[3:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    document = load()
    document.setdefault("mcpServers", {})[name] = {"command": rest[0], "args": rest[1:]}
    save(document)
elif argv[:2] == ["mcp", "remove"]:
    document = load()
    if argv[2] not in document.get("mcpServers", {}):
        sys.exit(1)
    del document["mcpServers"][argv[2]]
    save(document)
else:
    sys.exit(2)
