# 검증 기록

2026-11-02 / Linux / Python 3.12.3

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 18개 통과, MCP stdio 통합 테스트 1개 건너뜀.
- 실제 Git credential helper 프로토콜로 대상 저장소 토큰 제공과 다른 저장소 거부 확인. 가짜 토큰만 사용하고 네트워크는 호출하지 않음.
- 임시 Git 저장소에 커밋하여 세션별 작성자 정보 확인.
- 가짜 gh 실행 파일로 CLI 전체 실행, 계정 지정, 환경 변수 전달, 자식 종료 코드 반환 확인.
- 예제 설정 validate 및 resolve 실행 성공.
- 실제 계정별 GitHub API 호출, push, PR 생성과 Claude Code/Codex 실행은 미검증.
- MCP SDK 미설치. 현재 환경은 ensurepip/pip가 없어 MCP 의존성을 설치하지 못했음. CI는 MCP extra를 설치하고 stdio 통합 테스트를 실행하도록 구성함. CI 자체는 원격 게시 후 확인 필요.
- GitHub CLI 인증 확인은 API 네트워크 오류와 함께 실패했음. 저장된 자격 증명의 실제 유효성은 이 결과만으로 확정하지 않음.
