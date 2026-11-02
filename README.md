# GitHub Account Router

저장소에 맞춰 GitHub 계정을 선택하는 로컬 CLI와 MCP 서버입니다. Claude Code·Codex를 프로젝트별로 실행하거나, MCP 요청마다 다른 저장소 계정을 사용할 수 있습니다.

**상태: v0.1 초기판.** Linux/macOS CI와 Windows 실기기에서 검증했습니다. GitHub.com HTTPS 전용입니다. 실제 계정 연결 상태는 사용 환경에서 `doctor`로 확인하세요.

## 설치

Python 3.10+, Git, GitHub CLI(`gh`)가 필요합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[mcp]'
gh-router init
```

CLI만 사용한다면 `pip install -e .`로 설치할 수 있습니다. 계정마다 한 번씩 인증합니다.

Windows PowerShell에서는 `python -m venv .venv` 후 `.\.venv\Scripts\Activate.ps1`로 활성화하고 같은 설치 명령을 사용합니다.

pip 없이 CLI를 실행할 때는 `python3 gh_router.py`를 `gh-router` 대신 사용하세요. 예: `python3 gh_router.py --config config.example.json resolve --repo your-org/demo`. MCP 서버는 선택 의존성 설치가 필요합니다.

```bash
gh auth login --hostname github.com --git-protocol https
# 다른 계정도 위 명령으로 로그인합니다.
```

`~/.config/gh-router/config.json`의 계정 로그인명, 커밋 이름·이메일, 저장소 규칙을 수정합니다. [설정 예제](config.example.json)를 참고하세요. 이 파일에 토큰을 넣지 마세요. 인증은 GitHub CLI에 저장된 계정에서 가져옵니다.

## 프로젝트별 실행

```bash
gh-router validate
gh-router resolve --repo your-org/project
gh-router doctor --repo your-org/project
gh-router run --repo your-org/project -- claude
gh-router run --repo your-personal-login/project -- codex

# HTTPS origin이 설정된 프로젝트 폴더에서는 저장소 자동 감지
gh-router run -- codex
```

별도 설정 파일은 `gh-router --config /absolute/path/config.json run --repo owner/repo -- codex`처럼 지정합니다. 실행할 프로젝트 폴더에서 호출하세요. `--repo`는 작업 디렉터리를 바꾸지 않습니다.

정확한 저장소 규칙이 조직 규칙보다 우선합니다. 일치 규칙이 없으면 다른 계정으로 넘어가지 않고 종료합니다. 전역 Git 설정이나 `gh` 기본 계정을 바꾸지 않습니다.

## 공통 MCP 연결

MCP stdio 클라이언트에서 다음 실행 파일과 인자를 등록하세요. 경로는 설치한 가상 환경과 설정 파일의 절대 경로로 바꿉니다. 두 도구에 같은 서버를 등록할 수 있습니다.

```json
{
  "mcpServers": {
    "github-router": {
      "command": "/absolute/path/github-account-router/.venv/bin/gh-router",
      "args": ["--config", "/absolute/path/config.json", "mcp"]
    }
  }
}
```

이는 일반적인 MCP 서버 설정 예제이며 클라이언트마다 설정 파일 형식과 위치가 다를 수 있습니다.

도구: `resolve_account`, `get_repository`, `list_issues`, `read_file`. 모든 도구가 `repo: "owner/repo"`를 받습니다. 계정은 호출마다 다시 선택합니다. 설정에서 `allow_writes: true`로 변경하고 서버를 다시 시작하면 `create_pull_request`가 추가됩니다. PR은 초안으로 생성되며 코드는 먼저 push되어 있어야 합니다.

## 인증 범위

Git은 저장소 경로를 확인하는 credential helper로 인증합니다. GitHub API는 선택된 계정의 `GH_TOKEN`을 자식 프로세스에 전달합니다. 커밋 작성자와 커미터 정보도 해당 프로세스에서만 설정합니다.

`run`은 신뢰하는 프로그램을 실행하기 위한 도구입니다. 실행한 프로그램은 환경 변수의 토큰을 읽을 수 있으며 해당 토큰이 가진 전체 권한을 갖습니다. `GH_REPO`는 기본 저장소 지정이지 접근 권한 제한이 아닙니다. 세션 안에서 여러 저장소를 이동하면 API 계정은 그대로이므로, 새 `run` 또는 요청별 MCP 라우팅을 사용하세요. 환경 변수 방식은 장시간 세션 도중 토큰을 자동 갱신하지 않습니다.

SSH 원격, Enterprise, 브라우저의 기본 GitHub 연결 전환은 현재 범위에 포함되지 않습니다. Windows는 Git for Windows가 설치된 환경에서 테스트했습니다. 기존 인증용 HTTP 헤더가 설정된 환경에서는 CLI 실행을 거부합니다. 다른 계정이 필요한 서브모듈은 별도 세션으로 작업하세요.

## 테스트

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

기본 테스트는 네트워크와 실제 토큰 없이 수행합니다. MCP 선택 의존성을 설치하면 stdio 서버 통합 테스트도 실행합니다. Linux/macOS CI와 Windows 실기기에서 MCP를 포함한 19개 테스트를 통과했습니다.

실제 GitHub 계정으로 재현하려면 저장된 `gh` 인증과 MCP 의존성을 준비한 뒤 실행합니다.

```bash
python scripts/live_smoke.py --repo owner/repo --account your-login
# 선택: 다른 gh 계정 검증 및 설치된 두 CLI 시작 확인
python scripts/live_smoke.py --repo owner/repo --account your-login --second-account other-login --tool claude --tool codex
# 선택: 임시 브랜치 push와 초안 PR 생성·닫기·브랜치 삭제까지 검증
python scripts/live_smoke.py --repo owner/repo --account your-login --write
```

쓰기 테스트는 `main` 브랜치와 README가 있는 저장소에서 실행합니다. 테스트용 PR은 닫힌 기록으로 남고, 임시 브랜치는 삭제됩니다. 토큰은 출력하거나 파일로 저장하지 않습니다. [실행 검증 기록](docs/VALIDATION.ko.md)에 실제 결과를 기록했습니다.

기획과 후속 개발: [한국어 기획서](docs/PLAN.ko.md).

## 설계 참고

- [GitHub CLI 계정별 토큰 조회](https://cli.github.com/manual/gh_auth_token)
- [GitHub CLI 환경 변수 우선순위](https://cli.github.com/manual/gh_help_environment)
- [Git credential helper 프로토콜](https://git-scm.com/docs/gitcredentials)
- [공식 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

MIT License.
