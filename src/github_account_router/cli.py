from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .core import RouterError, check_git_auth_config, credential, infer_repo, load_config, repository, select, session_env, token_for

EXAMPLE = {
    "version": 1, "allow_writes": False,
    "accounts": {
        "personal": {"username": "your-personal-login", "name": "Your Name", "email": "personal@example.com"},
        "work": {"username": "your-work-login", "name": "Your Name", "email": "work@example.com"},
    },
    "rules": [{"repo": "your-org/*", "account": "work"},
              {"repo": "your-personal-login/*", "account": "personal"}],
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Route GitHub credentials per repository")
    parser.add_argument("--config", default=str(Path.home() / ".config/gh-router/config.json"))
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("init", help="Create config template without overwriting")
    subs.add_parser("validate", help="Validate configuration")
    for name in ("resolve", "doctor", "run"):
        sub = subs.add_parser(name)
        sub.add_argument("--repo", help="OWNER/REPO; defaults to current origin")
        if name == "run":
            sub.add_argument("command", nargs=argparse.REMAINDER)
    helper = subs.add_parser("credential", help=argparse.SUPPRESS)
    helper.add_argument("operation", choices=["get", "store", "erase"])
    subs.add_parser("mcp", help="Start optional MCP stdio server")
    args = parser.parse_args(argv)
    try:
        if args.action == "credential":
            sys.stdout.write(credential(args.operation, sys.stdin.read(65536), dict(os.environ)))
            return 0
        if args.action == "init":
            path = Path(args.config).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                json.dump(EXAMPLE, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            print(f"Created {path}; edit accounts and repository rules")
            return 0
        config = load_config(args.config)
        if args.action == "validate":
            print("Configuration valid")
            return 0
        if args.action == "mcp":
            from .server import serve
            serve(config)
            return 0
        repo = repository(args.repo) if args.repo else infer_repo()
        alias, account = select(config, repo)
        if args.action == "resolve":
            print(json.dumps({"repo": repo, "account": alias, "username": account["username"]}))
            return 0
        check_git_auth_config()
        token = token_for(account)
        env = session_env(account, repo, token)
        if args.action == "doctor":
            result = subprocess.run(["gh", "api", "user", "--jq", ".login"], env=env,
                                    capture_output=True, text=True, timeout=30)
            if result.returncode or result.stdout.strip().lower() != account["username"].lower():
                raise RouterError("Account identity verification failed")
            result = subprocess.run(["gh", "api", f"repos/{repo}", "--jq", ".full_name"],
                                    env=env, capture_output=True, text=True, timeout=30)
            if result.returncode or result.stdout.strip().lower() != repo:
                raise RouterError("Repository access verification failed")
            print(f"OK: {repo} -> {alias} ({account['username']})")
            return 0
        command = args.command
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise RouterError("Supply command after --")
        print(f"Routing {repo} -> {alias} ({account['username']})", file=sys.stderr)
        return subprocess.call(command, env=env)
    except (RouterError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"gh-router: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
