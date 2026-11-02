"""Optional official MCP SDK adapter. No arbitrary shell or URL tool is exposed."""
from urllib.parse import quote

from .core import RouterError, api, repository, select


def build_server(config):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RouterError('Install MCP support with: pip install -e ".[mcp]"') from exc
    server = FastMCP("github-account-router")

    @server.tool()
    def resolve_account(repo: str) -> dict:
        """Preview account routing without exposing credentials."""
        alias, account = select(config, repo)
        return {"repo": repository(repo), "account": alias, "username": account["username"]}

    @server.tool()
    def get_repository(repo: str) -> dict:
        """Read GitHub repository metadata using its configured account."""
        return api(config, repo)

    @server.tool()
    def list_issues(repo: str) -> list:
        """Read the first 30 open issues (GitHub also includes pull requests)."""
        return api(config, repo, "/issues?state=open&per_page=30")

    @server.tool()
    def read_file(repo: str, path: str, ref: str = "HEAD") -> dict:
        """Read a file through the contents API; content is normally base64 encoded."""
        if not path or path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
            raise RouterError("Expected a relative repository file path")
        return api(config, repo, "/contents/" + quote(path, safe="/") + "?ref=" + quote(ref, safe=""))

    if config.get("allow_writes", False):
        @server.tool()
        def create_pull_request(repo: str, title: str, head: str, base: str, body: str = "") -> dict:
            """Create a draft pull request. Changes must already be pushed."""
            if not all(v.strip() for v in (title, head, base)):
                raise RouterError("title, head and base are required")
            return api(config, repo, "/pulls", {"title": title, "head": head, "base": base,
                                               "body": body, "draft": True})
    return server


def serve(config):
    build_server(config).run(transport="stdio")
