"""Routing and subprocess isolation. Tokens are never persisted by the router."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


class RouterError(ValueError):
    pass


def repository(value: str) -> str:
    """Accept canonical names and GitHub HTTPS remotes, reject credentials/SSH."""
    if value.startswith("https://"):
        url = urlsplit(value)
        if url.netloc.lower() != "github.com" or url.query or url.fragment:
            raise RouterError("Only credential-free github.com HTTPS remotes are supported")
        value = url.path.removeprefix("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value):
        raise RouterError("Expected OWNER/REPO or https://github.com/OWNER/REPO.git")
    owner, name = value.split("/")
    if name in (".", ".."):
        raise RouterError("Invalid repository name")
    return f"{owner}/{name}".lower()


def load_config(path: str) -> dict:
    try:
        config = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouterError("Cannot read config; use init or check JSON syntax") from exc
    if not isinstance(config, dict) or config.get("version") != 1:
        raise RouterError("Config version must be 1")
    accounts, rules = config.get("accounts"), config.get("rules")
    if not isinstance(accounts, dict) or not accounts or not isinstance(rules, list) or not rules:
        raise RouterError("Non-empty accounts and rules are required")
    for alias, account in accounts.items():
        if not isinstance(account, dict) or set(account) != {"username", "name", "email"}:
            raise RouterError(f"Account {alias}: expected username, name, email only")
        if any(not isinstance(v, str) or not v.strip() or any(c in v for c in "\r\n\0")
               for v in account.values()):
            raise RouterError(f"Account {alias}: invalid identity")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", account["username"]):
            raise RouterError(f"Account {alias}: invalid GitHub username")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"repo", "account"}:
            raise RouterError("Rules must contain repo and account only")
        pattern = rule["repo"]
        if not isinstance(pattern, str):
            raise RouterError("Repository rule must be a string")
        if pattern.endswith("/*"):
            repository(pattern[:-1] + "example")
        else:
            repository(pattern)
        if pattern != pattern.lower() or pattern.endswith(".git") or pattern.startswith("https:"):
            raise RouterError("Rules must be lowercase owner/repo or owner/*")
        if pattern in seen or rule["account"] not in accounts:
            raise RouterError("Duplicate rule or unknown account")
        seen.add(pattern)
    if not isinstance(config.get("allow_writes", False), bool):
        raise RouterError("allow_writes must be a boolean")
    return config


def select(config: dict, repo: str) -> tuple[str, dict]:
    repo = repository(repo)
    exact = [r for r in config["rules"] if r["repo"] == repo]
    matches = exact or [r for r in config["rules"] if fnmatch.fnmatchcase(repo, r["repo"])]
    if len(matches) != 1:
        raise RouterError("Repository needs exactly one matching rule")
    alias = matches[0]["account"]
    return alias, config["accounts"][alias]


def clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key in {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
                   "GH_HOST", "GH_REPO", "GIT_ASKPASS", "SSH_ASKPASS"} or key.startswith("GIT_CONFIG_"):
            env.pop(key)
    return env


def token_for(account: dict) -> str:
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com", "--user", account["username"]],
            env=clean_env(), capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RouterError("Cannot invoke gh; install GitHub CLI and log in first") from exc
    token = result.stdout.strip()
    if result.returncode or not token or any(c in token for c in "\r\n\0"):
        raise RouterError(f"No usable gh credential for {account['username']}; log in with gh auth login")
    return token


def infer_repo(cwd: str | None = None) -> str:
    result = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd,
                            capture_output=True, text=True)
    if result.returncode:
        raise RouterError("Cannot infer origin; supply --repo")
    return repository(result.stdout.strip())


def check_git_auth_config(cwd: str | None = None) -> None:
    """Reject preconfigured headers that may override the credential helper."""
    result = subprocess.run(
        ["git", "config", "--get-regexp", r"^http\..*extraheader$"], cwd=cwd,
        env=clean_env(), capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        raise RouterError("Cannot inspect Git HTTP authentication configuration")
    # Do not echo header values: these may contain credentials.
    if any(len(line.split(None, 1)) == 2 and line.split(None, 1)[1].strip()
           for line in result.stdout.splitlines()):
        raise RouterError("Existing Git HTTP extraHeader found; remove it before routed sessions")


def session_env(account: dict, repo: str, token: str) -> dict[str, str]:
    repo = repository(repo)
    env = clean_env()
    # A helper is invoked by Git's shell; quote paths, never interpolate tokens.
    helper = "!" + shlex.join([sys.executable, "-m", "github_account_router.cli", "credential"])
    settings = [
        ("credential.helper", ""), ("credential.helper", helper),
        ("credential.useHttpPath", "true"),
        ("http.extraHeader", ""),
        ("http.https://github.com/.extraHeader", ""),
        ("http.https://github.com/" + repo + ".extraHeader", ""),
    ]
    env["GIT_CONFIG_COUNT"] = str(len(settings))
    for i, (key, value) in enumerate(settings):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    env.update(GH_TOKEN=token, GITHUB_TOKEN=token, GH_HOST="github.com", GH_REPO=repo,
               GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1",
               GIT_AUTHOR_NAME=account["name"], GIT_AUTHOR_EMAIL=account["email"],
               GIT_COMMITTER_NAME=account["name"], GIT_COMMITTER_EMAIL=account["email"],
               GH_ROUTER_REPO=repo, GH_ROUTER_USER=account["username"])
    return env


def credential(operation: str, data: str, env: dict[str, str]) -> str:
    if operation != "get":
        return ""
    fields = dict(line.split("=", 1) for line in data.splitlines() if "=" in line)
    expected = env.get("GH_ROUTER_REPO", "")
    if fields.get("protocol") != "https" or fields.get("host", "").lower() != "github.com":
        return "quit=true\n\n"
    try:
        actual = repository(fields.get("path", ""))
    except RouterError:
        return "quit=true\n\n"
    if actual != expected or not env.get("GH_TOKEN") or not env.get("GH_ROUTER_USER"):
        return "quit=true\n\n"
    if fields.get("username") not in (None, "", env["GH_ROUTER_USER"]):
        return "quit=true\n\n"
    return f"username={env['GH_ROUTER_USER']}\npassword={env['GH_TOKEN']}\n\n"


def api(config: dict, repo: str, suffix: str = "", payload: dict | None = None):
    repo = repository(repo)
    _, account = select(config, repo)
    if payload is not None and not config.get("allow_writes", False):
        raise RouterError("MCP writes disabled; explicitly enable allow_writes in config")
    env = clean_env()
    env["GH_TOKEN"] = token_for(account)
    env["GH_HOST"] = "github.com"
    command = ["gh", "api", f"repos/{repo}{suffix}"]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    try:
        result = subprocess.run(command, env=env, input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RouterError("GitHub API invocation failed or timed out") from exc
    if result.returncode:
        raise RouterError("GitHub API failed; check selected account permissions and connectivity")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RouterError("GitHub returned an unexpected response") from exc
