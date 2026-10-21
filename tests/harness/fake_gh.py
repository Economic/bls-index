"""A stand-in for the `gh` command, for testing scripts/publish.sh offline.

Releases live in the JSON file named by FAKE_GH_STATE, and every call is appended to
FAKE_GH_LOG. Environment switches make GitHub misbehave:
  FAKE_GH_BAD_DIGEST=1    uploaded parquet gets a wrong digest
  FAKE_GH_LOSE_PUBLISH=1  the publish takes effect, but the call reports failure
  FAKE_GH_FAIL_PUBLISH=1  the publish fails and does not take effect
  FAKE_GH_FAIL_DELETE=1   deleting a release fails
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_GH_STATE"])


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"releases": [], "latest": None, "next_id": 1}


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state))


def flags(args: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    positional, named, i = [], {}, 0
    while i < len(args):
        if args[i] in ("--draft", "--prerelease"):  # flags without a value
            i += 1
        elif args[i].startswith("-"):
            named.setdefault(args[i], []).append(args[i + 1])
            i += 2
        else:
            positional.append(args[i])
            i += 1
    return positional, named


def main(args: list[str]) -> int:
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(json.dumps(args) + "\n")
    state = load()
    releases = state["releases"]
    if args[:2] == ["release", "create"]:
        positional, named = flags(args[2:])
        tag, files = positional[0], positional[1:]
        assets = []
        for path in map(Path, files):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if os.environ.get("FAKE_GH_BAD_DIGEST") and path.name.endswith(".parquet"):
                digest = "0" * 64
            assets.append({"name": path.name, "size": path.stat().st_size, "digest": f"sha256:{digest}"})
        releases.append({
            "id": state["next_id"], "tag_name": tag, "draft": "--draft" in args,
            "prerelease": "--prerelease" in args, "created_at": f"2026-10-{state['next_id']:02d}",
            "assets": assets,
        })  # fmt: skip
        state["next_id"] += 1
        save(state)
        return 0
    if args[0] != "api":
        print(f"fake gh: unsupported {args}", file=sys.stderr)
        return 2
    positional, named = flags(args[1:])
    method, path = named.get("-X", ["GET"])[0], positional[0].split("?")[0]
    fields = dict(f.split("=", 1) for f in named.get("-F", []) + named.get("-f", []))
    parts = path.split("/")  # repos, owner, repo, ...
    if method == "GET" and parts[3:] == ["releases"]:
        print(json.dumps(releases))
        return 0
    if method == "GET" and parts[3:] == ["releases", "latest"]:
        found = [r for r in releases if r["tag_name"] == state["latest"]]
        if not found:
            return 1
        return output(found[0], named)
    if parts[3] == "releases" and len(parts) == 5:
        release = next((r for r in releases if r["id"] == int(parts[4])), None)
        if release is None:
            return 1
        if method == "GET":
            return output(release, named)
        if method == "DELETE":
            if os.environ.get("FAKE_GH_FAIL_DELETE"):
                return 1
            releases.remove(release)
            save(state)
            return 0
        if method == "PATCH":
            if os.environ.get("FAKE_GH_FAIL_PUBLISH"):
                return 1
            release["draft"] = fields.get("draft") != "false" and release["draft"]
            if fields.get("make_latest") == "true":
                state["latest"] = release["tag_name"]
            save(state)
            return 1 if os.environ.get("FAKE_GH_LOSE_PUBLISH") else 0
    if method == "DELETE" and parts[3:5] == ["git", "refs"]:
        return 0
    print(f"fake gh: unsupported {args}", file=sys.stderr)
    return 2


def output(release: dict, named: dict) -> int:
    jq = named.get("--jq", [None])[0]
    if jq is None:
        print(json.dumps(release))
    else:  # like gh: strings print raw, everything else as JSON
        value = release[jq.lstrip(".")]
        print(value if isinstance(value, str) else json.dumps(value))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
