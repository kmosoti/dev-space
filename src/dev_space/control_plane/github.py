from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Protocol


class GitHubError(RuntimeError):
    """Base class for typed GitHub adapter failures."""


class GitHubAuthenticationError(GitHubError):
    """The active gh configuration is not authenticated."""


class GitHubAuthorizationError(GitHubError):
    """The active actor lacks a required permission."""


class GitHubConflictError(GitHubError):
    """Live GitHub state conflicts with a unique desired resource."""


class GitHubResponseError(GitHubError):
    """GitHub returned invalid JSON or a GraphQL error."""


class GhRunner(Protocol):
    def run(self, arguments: list[str], input_text: str | None = None) -> str: ...


class SubprocessGhRunner:
    def run(self, arguments: list[str], input_text: str | None = None) -> str:
        result = subprocess.run(
            ["gh", *arguments],
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        message = result.stderr.strip() or result.stdout.strip() or "gh command failed"
        normalized = message.casefold()
        if "authentication" in normalized or "not logged" in normalized:
            raise GitHubAuthenticationError(message)
        if "forbidden" in normalized or "resource not accessible" in normalized:
            raise GitHubAuthorizationError(message)
        raise GitHubError(message)


class GitHubClient:
    def __init__(self, runner: GhRunner | None = None):
        self.runner = runner or SubprocessGhRunner()

    def graphql(
        self, query: str, variables: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        payload = {"query": query, "variables": dict(variables or {})}
        raw = self.runner.run(["api", "graphql", "--input", "-"], json.dumps(payload))
        response = self._decode(raw)
        errors = response.get("errors")
        if errors:
            raise GitHubResponseError(
                f"GraphQL errors: {json.dumps(errors, sort_keys=True)}"
            )
        data = response.get("data")
        if not isinstance(data, dict):
            raise GitHubResponseError(
                "GraphQL response is missing an object data field"
            )
        return data

    def rest(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        payload: Mapping[str, object] | None = None,
    ) -> object:
        arguments = ["api", endpoint, "--method", method]
        input_text = None
        if payload is not None:
            arguments.extend(["--input", "-"])
            input_text = json.dumps(dict(payload))
        raw = self.runner.run(arguments, input_text)
        if not raw.strip():
            return None
        return self._decode(raw)

    def current_user(self) -> str:
        response = self.rest("user")
        if not isinstance(response, dict) or not isinstance(response.get("login"), str):
            raise GitHubResponseError("user response is missing login")
        return response["login"]

    @staticmethod
    def _decode(raw: str) -> dict[str, object] | list[object]:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GitHubResponseError("gh returned invalid JSON") from exc
        if not isinstance(decoded, (dict, list)):
            raise GitHubResponseError("gh returned a non-container JSON value")
        return decoded
