# 실행 검증 기록

검증일: 2026-11-02

## 자동화 테스트

| 실행 환경 | 결과 |
|---|---|
| Linux 로컬 / Python 3.12.3 / MCP 미설치 | 18개 통과, MCP 테스트 1개 생략 |
| GitHub Actions / Ubuntu·macOS / Python 3.10·3.12·3.13 | 6개 조합 전부 통과; MCP SDK 설치 및 stdio 연결 포함 |
| Windows 10 실기기 / Python 3.11.8 / MCP 1.30.0 / Git for Windows | 19개 전부 통과, 생략 없음 |

기존 Linux/macOS CI 결과: [성공한 실행](https://github.com/devdevra/github-account-router/actions/runs/41402136835).

Windows 실행 중 발견한 가짜 `gh` 실행 파일 탐색 문제를 수정했다. 계정 토큰 조회는 `shutil.which`로 실행 파일 경로를 찾으며, Windows 테스트에서는 `.cmd` 실행 파일을 생성한다. CI에도 Windows를 추가했다.

## 실제 GitHub 계정 검증

별도 테스트 디렉터리와 격리된 Python 실행 환경을 사용했다. 기존 Python 패키지나 GitHub 기본 계정을 변경하지 않았다. 인증값을 출력하거나 저장소에 커밋하지 않았다.

- `devdevra` 및 `contentscoin`의 저장된 `gh` 인증을 각각 선택하고 실제 `/user` 응답으로 확인.
- `doctor`: 선택한 계정의 사용자 신원과 `devdevra/github-account-router` 접근 확인.
- `run`: 자식 프로세스의 `gh api user`가 선택한 사용자로 실행되는 것 확인.
- 실제 Git credential helper로 대상 저장소에 자격 증명이 제공되는 것 확인.
- 별도 checkout에서 작성자 정보를 지정한 테스트 커밋을 만들고 HTTPS push 성공.
- MCP stdio 초기화·도구 목록·저장소 조회·README 읽기·이슈 목록 조회 성공.
- 같은 MCP 세션에서 두 저장소 요청을 서로 다른 실제 계정으로 처리.
- 미등록 저장소 요청 거부.
- MCP로 [테스트용 초안 PR #1](https://github.com/devdevra/github-account-router/pull/1) 생성 성공.
- PR은 닫았으며 병합하지 않음. 테스트용 원격 브랜치 삭제 완료.
- 검사 전후 전역 활성 GitHub 계정이 동일한 것 확인.
- 라우터를 통해 Claude Code `2.1.283`과 Codex CLI `0.154.0`의 `--version` 실행 성공.

## 재현

```bash
python scripts/live_smoke.py --repo owner/repo --account your-login --second-account other-login --write
```

`--write`를 빼면 push와 PR 생성 없이 읽기 검사만 실행한다. `--tool claude --tool codex`를 추가하면 설치된 두 실행 파일을 라우터로 시작하여 `--version`을 확인한다. 각 계정은 사전에 `gh auth login`으로 인증되어 있어야 한다.

## 남은 범위

실제 AI 모델 요청으로 코드를 수정하는 대화와 Claude Code/Codex 앱 설정에 MCP 서버를 등록하는 절차는 이번 검사에 포함하지 않았다. SSH, GitHub Enterprise, 토큰 자동 갱신은 현재 구현 범위에 포함되지 않는다.
