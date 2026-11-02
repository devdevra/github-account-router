import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from github_account_router import core
from github_account_router.cli import EXAMPLE, main


def config():
    return {
        "version": 1, "accounts": {
            "work": {"username": "worker", "name": "Work User", "email": "work@example.com"},
            "personal": {"username": "person", "name": "Personal User", "email": "me@example.com"},
        },
        "rules": [{"repo": "company/*", "account": "work"},
                  {"repo": "company/private", "account": "personal"}],
    }


class RoutingTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(core.repository("https://github.com/Company/App.git"), "company/app")

    def test_rejects_unsafe_targets(self):
        for value in ["git@github.com:o/r.git", "https://evil.com/o/r", "https://x@github.com/o/r",
                      "https://github.com/o/r?q=a", "o/r/other", "o/..", "o/r\n", "https://github.com:443/o/r"]:
            with self.subTest(value=value), self.assertRaises(core.RouterError):
                core.repository(value)

    def test_exact_rule_precedes_owner(self):
        self.assertEqual(core.select(config(), "company/private")[0], "personal")
        self.assertEqual(core.select(config(), "company/app")[0], "work")

    def test_no_fallback(self):
        with self.assertRaises(core.RouterError):
            core.select(config(), "unknown/repo")

    def test_ambiguous_match_fails(self):
        cfg = config()
        cfg["rules"].append(cfg["rules"][0])
        with self.assertRaises(core.RouterError):
            core.select(cfg, "company/app")

    def test_config_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(config()))
            self.assertEqual(core.load_config(str(path))["version"], 1)
            cfg = config()
            cfg["accounts"]["work"]["token"] = "must-not-be-stored"
            path.write_text(json.dumps(cfg))
            with self.assertRaises(core.RouterError):
                core.load_config(str(path))

    def test_init_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
            path = Path(tmp) / "config.json"
            self.assertEqual(main(["--config", str(path), "init"]), 0)
            self.assertEqual(main(["--config", str(path), "init"]), 2)
            self.assertEqual(json.loads(path.read_text()), EXAMPLE)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.account = config()["accounts"]["work"]

    def test_sessions_do_not_change_parent_or_each_other(self):
        with patch.dict(os.environ, {"GH_TOKEN": "ambient", "GIT_CONFIG_COUNT": "1",
                                     "GIT_CONFIG_KEY_0": "bad", "GIT_CONFIG_VALUE_0": "bad"}):
            a = core.session_env(self.account, "company/a", "token-a")
            b = core.session_env(config()["accounts"]["personal"], "company/private", "token-b")
            self.assertEqual(os.environ["GH_TOKEN"], "ambient")
            self.assertEqual((a["GH_TOKEN"], b["GH_TOKEN"]), ("token-a", "token-b"))
            self.assertEqual(a["GIT_AUTHOR_EMAIL"], "work@example.com")
            self.assertEqual(a["GIT_CONFIG_VALUE_0"], "")

    def test_token_lookup_is_explicit_and_ignores_ambient_token(self):
        with patch.dict(os.environ, {"GH_TOKEN": "ambient"}), patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "secret\n", "")
            self.assertEqual(core.token_for(self.account), "secret")
            args, kwargs = run.call_args
            self.assertEqual(args[0][-2:], ["--user", "worker"])
            self.assertNotIn("GH_TOKEN", kwargs["env"])

    def test_lookup_failure_does_not_leak_stderr(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "secret")):
            with self.assertRaises(core.RouterError) as caught:
                core.token_for(self.account)
            self.assertNotIn("secret", str(caught.exception))

    def test_header_conflicts_fail_without_leaking(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0,
                   "http.https://github.com/.extraheader AUTHORIZATION: secret\n", "")):
            with self.assertRaises(core.RouterError) as caught:
                core.check_git_auth_config()
            self.assertNotIn("secret", str(caught.exception))

    def test_credential_target_is_bound(self):
        env = core.session_env(self.account, "company/app", "secret")
        good = "protocol=https\nhost=github.com\npath=company/app.git\n"
        self.assertIn("password=secret", core.credential("get", good, env))
        for data in [good.replace("app.git", "other.git"), good.replace("github.com", "evil.com"),
                     good.replace("https", "http"), good + "username=person\n", "protocol=https\nhost=github.com\n"]:
            self.assertEqual(core.credential("get", data, env), "quit=true\n\n")
        self.assertEqual(core.credential("store", good, env), "")

    def test_real_git_credential_helper(self):
        env = core.session_env(self.account, "company/app", "fake-integration-token")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        with tempfile.TemporaryDirectory() as tmp:
            # No network: exercise Git's real helper subprocess protocol.
            for repo, code in [("company/app.git", 0), ("company/other.git", 128)]:
                result = subprocess.run(["git", "credential", "fill"], cwd=tmp, env=env,
                                        input=f"protocol=https\nhost=github.com\npath={repo}\n\n",
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, code, result.stderr)
                if code == 0:
                    self.assertIn("password=fake-integration-token", result.stdout)
                else:
                    self.assertNotIn("fake-integration-token", result.stdout)

    def test_real_git_commit_identity_is_session_local(self):
        env = core.session_env(self.account, "company/app", "fake")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "test"],
                           cwd=tmp, env=env, check=True)
            identity = subprocess.check_output(["git", "show", "-s", "--format=%an <%ae>"], cwd=tmp, text=True)
            self.assertEqual(identity.strip(), "Work User <work@example.com>")

    def test_read_api_routes_each_call(self):
        with patch("github_account_router.core.token_for", side_effect=["work-token", "personal-token"]), patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "{}", "")
            core.api(config(), "company/app")
            core.api(config(), "company/private")
            self.assertEqual([c.kwargs["env"]["GH_TOKEN"] for c in run.call_args_list],
                             ["work-token", "personal-token"])

    def test_write_api_disabled_before_credentials(self):
        with patch("github_account_router.core.token_for") as token:
            with self.assertRaises(core.RouterError):
                core.api(config(), "company/app", "/pulls", {"title": "test"})
            token.assert_not_called()

    def test_write_api_uses_stdin_and_draft_payload(self):
        cfg = config() | {"allow_writes": True}
        with patch("github_account_router.core.token_for", return_value="secret"), patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, '{"number":1}', "")
            self.assertEqual(core.api(cfg, "company/app", "/pulls", {"draft": True}), {"number": 1})
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"draft": True})
            self.assertNotIn("secret", str(run.call_args.args))

    def test_cli_run_end_to_end_with_fake_gh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config.json"
            cfg.write_text(json.dumps(config()))
            fake = root / ("gh_stub.py" if os.name == "nt" else "gh")
            fake.write_text(f"#!{sys.executable}\nimport sys\n"
                            "assert sys.argv[1:3] == ['auth', 'token']\n"
                            "assert sys.argv[-2:] == ['--user', 'worker']\n"
                            "print('fake-child-token')\n")
            fake.chmod(0o700)
            if os.name == "nt":
                (root / "gh.cmd").write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\n', encoding="utf-8")
            env = dict(os.environ)
            env["PATH"] = str(root) + os.pathsep + env.get("PATH", "")
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            env["GH_TOKEN"] = "ambient-token"
            child = ("import os,sys; "
                     "assert os.environ['GH_TOKEN']=='fake-child-token'; "
                     "assert os.environ['GH_REPO']=='company/app'; "
                     "assert os.environ['GIT_AUTHOR_EMAIL']=='work@example.com'; "
                     "sys.exit(7)")
            result = subprocess.run([sys.executable, "-m", "github_account_router.cli",
                "--config", str(cfg), "run", "--repo", "company/app", "--", sys.executable, "-c", child],
                cwd=tmp, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertNotIn("fake-child-token", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
