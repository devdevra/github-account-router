"""Run opt-in live GitHub tests without printing or saving credentials.

Example: python scripts/live_smoke.py --repo owner/repo --account owner
Add --second-account OTHER to verify a second saved gh identity.
Add --write to push a temporary branch and open/close a draft PR.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from github_account_router.core import (
    RouterError, clean_env, repository, session_env, token_for,
)


def checked(command, *, env=None, cwd=None, data=None):
    result = subprocess.run(command, env=env, cwd=cwd, input=data,
                            text=True, capture_output=True, timeout=90)
    if result.returncode:
        # Do not include commands, stderr or stdout: these may include credentials.
        raise RouterError(f"{Path(command[0]).stem} invocation failed (exit {result.returncode})")
    return result.stdout.strip()


def identity(username):
    return {"username": username, "name": "GitHub Router Smoke Test",
            "email": f"{username}@users.noreply.github.com"}


async def mcp_checks(config_path, repo, second_repo=None, branch=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = clean_env()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / "gh_router.py"), "--config", str(config_path), "mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert ("create_pull_request" in names) == bool(branch)

            async def call(name, args):
                result = await session.call_tool(name, args)
                if result.isError:
                    raise RouterError(f"MCP tool failed: {name}")
                if not result.content:
                    return result.structuredContent or []
                return json.loads(result.content[0].text)

            route = await call("resolve_account", {"repo": repo})
            assert route["account"] == "primary"
            metadata = await call("get_repository", {"repo": repo})
            assert metadata["full_name"].lower() == repo
            contents = await call("read_file", {"repo": repo, "path": "README.md"})
            assert contents["type"] == "file"
            await call("list_issues", {"repo": repo})
            if second_repo:
                route = await call("resolve_account", {"repo": second_repo})
                assert route["account"] == "secondary"
                metadata = await call("get_repository", {"repo": second_repo})
                assert metadata["full_name"].lower() == second_repo
            rejected = await session.call_tool("resolve_account", {"repo": "unconfigured-router-test/unknown"})
            assert rejected.isError
            if branch:
                pr = await call("create_pull_request", {
                    "repo": repo, "title": "Router execution smoke test (temporary)",
                    "head": branch, "base": "main",
                    "body": "Automated account-router execution verification. Closed after testing; do not merge.",
                })
                assert pr["draft"]
                return pr["number"]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--second-account")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--tool", action="append", choices=["claude", "codex"], default=[],
                        help="Launch installed coding CLI with --version through the router")
    args = parser.parse_args()
    repo = repository(args.repo)
    account = identity(args.account)
    report = {"repo": repo, "account": args.account, "checks": []}
    primary_env = session_env(account, repo, token_for(account))
    assert checked(["gh", "api", "user", "--jq", ".login"], env=primary_env).lower() == args.account.lower()
    report["checks"].append("primary GitHub identity")
    active_before = checked(["gh", "api", "user", "--jq", ".login"], env=clean_env())
    cfg = {"version": 1, "allow_writes": args.write,
           "accounts": {"primary": account}, "rules": [{"repo": repo, "account": "primary"}]}
    second_repo = None
    if args.second_account:
        secondary = identity(args.second_account)
        secondary_env = session_env(secondary, repo, token_for(secondary))
        assert checked(["gh", "api", "user", "--jq", ".login"], env=secondary_env).lower() == args.second_account.lower()
        report["checks"].append("secondary GitHub identity")
        # Public repository discovery only; no private repository names enter the report.
        repos = json.loads(checked(["gh", "api", f"users/{args.second_account}/repos?per_page=1"], env=secondary_env))
        if repos:
            second_repo = repository(repos[0]["full_name"])
            if second_repo != repo:
                cfg["accounts"]["secondary"] = secondary
                cfg["rules"].append({"repo": second_repo, "account": "secondary"})
            else:
                second_repo = None
    branch = "router-smoke-" + uuid.uuid4().hex[:12] if args.write else None
    pr_number = None
    pushed = False
    with tempfile.TemporaryDirectory(prefix="gh-router-live-") as tmp:
        folder = Path(tmp)
        config_path = folder / "config.json"
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        base = [sys.executable, str(ROOT / "gh_router.py"), "--config", str(config_path)]
        checked(base + ["doctor", "--repo", repo], env=clean_env(), cwd=folder)
        report["checks"].append("CLI doctor authenticates and reads repository")
        login = checked(base + ["run", "--repo", repo, "--", "gh", "api", "user", "--jq", ".login"],
                        env=clean_env(), cwd=folder)
        assert login.lower() == args.account.lower()
        report["checks"].append("CLI run injects selected real identity")
        for tool in args.tool:
            executable = shutil.which(tool)
            if not executable:
                raise RouterError(f"{tool} is not installed")
            version = checked(base + ["run", "--repo", repo, "--", executable, "--version"],
                              env=clean_env(), cwd=folder)
            report.setdefault("tool_versions", {})[tool] = version
            report["checks"].append(f"CLI run launches installed {tool} --version")
        request = f"protocol=https\nhost=github.com\npath={repo}.git\n\n"
        credentials = checked(["git", "credential", "fill"], env=primary_env, cwd=folder, data=request)
        assert "password=" in credentials and f"username={args.account}" in credentials
        del credentials
        report["checks"].append("real Git credential helper")
        try:
            if branch:
                checkout = folder / "checkout"
                checked(["git", "clone", "--quiet", "--single-branch", "--branch", "main",
                         f"https://github.com/{repo}.git", str(checkout)], env=primary_env)
                checked(["git", "checkout", "-qb", branch], env=primary_env, cwd=checkout)
                (checkout / "router-smoke-test.txt").write_text("Temporary live account-router smoke test.\n")
                checked(["git", "add", "router-smoke-test.txt"], env=primary_env, cwd=checkout)
                checked(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "Temporary router execution test"],
                        env=primary_env, cwd=checkout)
                author = checked(["git", "show", "-s", "--format=%an <%ae>"], env=primary_env, cwd=checkout)
                assert author == f"{account['name']} <{account['email']}>"
                checked(["git", "push", "--quiet", "origin", branch], env=primary_env, cwd=checkout)
                pushed = True
                report["checks"].append("HTTPS Git push with isolated author")
            pr_number = asyncio.run(mcp_checks(config_path, repo, second_repo, branch))
            report["checks"].extend(["MCP stdio initialization and tool listing",
                "MCP authenticated repository/file/issue reads", "MCP rejects unconfigured repository"])
            if second_repo:
                report["checks"].append("same MCP session routes two real accounts")
            if pr_number:
                report["checks"].append("MCP creates real draft pull request")
                report["test_pr"] = pr_number
        finally:
            if pr_number:
                checked(["gh", "api", f"repos/{repo}/pulls/{pr_number}", "--method", "PATCH", "-f", "state=closed"],
                        env=primary_env)
                report["checks"].append("test pull request closed")
            if pushed:
                checked(["gh", "api", f"repos/{repo}/git/refs/heads/{branch}", "--method", "DELETE"], env=primary_env)
                report["checks"].append("temporary remote branch deleted")
        active_after = checked(["gh", "api", "user", "--jq", ".login"], env=clean_env())
        assert active_before == active_after
        report["checks"].append("global active GitHub account unchanged")
        # Git for Windows may retain file handles briefly; keep local test artifacts
        # outside the checkout and let TemporaryDirectory perform its normal cleanup.
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
