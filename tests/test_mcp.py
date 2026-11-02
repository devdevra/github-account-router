"""Real SDK/stdio integration; enabled by installing the mcp extra."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from test_router import config


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK not installed")
class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initialization_tools_and_request_routing(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            cfg.write_text(json.dumps(config()))
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "github_account_router.cli", "--config", str(cfg), "mcp"], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools},
                                     {"resolve_account", "get_repository", "list_issues", "read_file"})
                    for repo, expected in [("company/app", "work"), ("company/private", "personal")]:
                        result = await session.call_tool("resolve_account", {"repo": repo})
                        self.assertFalse(result.isError)
                        payload = json.loads(result.content[0].text)
                        self.assertEqual(payload["account"], expected)
                    result = await session.call_tool("resolve_account", {"repo": "unknown/repo"})
                    self.assertTrue(result.isError)
