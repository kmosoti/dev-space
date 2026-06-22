#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from dev_space.control_plane.pr_contract import validate_pull_request_contract


def api(path: str):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API {path} failed with HTTP {exc.code}") from exc


def main() -> int:
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    pull_request = event["pull_request"]
    repository = event["repository"]["full_name"]
    body = pull_request.get("body") or ""
    import re

    links = re.findall(
        r"(?im)^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\s*$",
        body,
    )
    issue = (
        api(f"/repos/{repository}/issues/{links[0]}") if len(set(links)) == 1 else None
    )
    comments = (
        api(f"/repos/{repository}/issues/{links[0]}/comments?per_page=100")
        if issue is not None
        else []
    )
    commits = api(
        f"/repos/{repository}/pulls/{pull_request['number']}/commits?per_page=100"
    )
    if not commits:
        raise RuntimeError("pull request has no commits")
    first_commit_at = datetime.fromisoformat(
        commits[0]["commit"]["author"]["date"].replace("Z", "+00:00")
    )
    result = validate_pull_request_contract(
        body=body,
        head_ref=pull_request["head"]["ref"],
        author=pull_request["user"]["login"],
        issue=issue,
        comments=comments,
        first_commit_at=first_commit_at,
        planner="kmosoti",
        worker="kz-harbringer",
    )
    print(json.dumps({"issue": result.issue_number, "violations": result.violations}))
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
