# Polymarket Morning Briefing

Polymarket 공개 시장 데이터를 읽어 매일 아침 한국어 요약 알림을 보내는 read-only 브리핑 봇입니다. 주문, 지갑 서명, 포지션 관리, 투자 조언 기능은 없습니다.

## 설치

Python 3.11 이상이 필요합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 설정

```bash
cp config.example.yaml config.yaml
```

`config.yaml`에서 watchlist slug, discovery keyword, 점수 기준, 알림 provider를 조정합니다. 민감정보는 `config.yaml`에 쓰지 말고 환경변수나 GitHub Secrets로 설정합니다.

시크릿은 환경변수를 먼저 읽고, 값이 없으면 저장소 루트의 `keys` 파일에서 `NAME=value` 형식으로 찾습니다. `#`으로 시작하는 줄은 무시하고 이름은 대소문자를 구분하지 않으며, `NTFY_TOPIC`은 `ntfy`, `OPENROUTER_API_KEY`는 `openrouter`라는 이름으로도 인식합니다. `keys`는 `.gitignore`에 포함되어 있고 절대 커밋하지 않습니다.

## ntfy 설정

ntfy 앱을 설치한 뒤 추측하기 어려운 topic을 정하고 환경변수로 설정합니다.

```bash
export NTFY_TOPIC="your-hard-to-guess-topic"
```

기본 provider는 ntfy입니다. 알림은 `https://ntfy.sh/<topic>`으로 전송됩니다.

## Telegram 선택 설정

`config.yaml`에서 `notification.provider: telegram`으로 바꾼 뒤 환경변수를 설정합니다.

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

## 로컬 실행

알림 없이 stdout으로 확인합니다.

```bash
polymarket-briefing run --config config.example.yaml --dry-run
```

watchlist 정규화 결과만 확인하려면:

```bash
polymarket-briefing fetch-watchlist --config config.example.yaml
```

활성 시장 discovery 점수를 확인하려면:

```bash
polymarket-briefing discover --config config.example.yaml
```

## 배포/운영

매일 08:07 KST 정기 실행은 홈서버(`pi-control`)의 systemd user timer가 담당합니다. unit 파일과 배포 스크립트는 [`systemd/`](systemd/)에 있으며, **실제 서버에서 그대로 가져온 것**입니다.

**검증한 코드를 `main`에 push하면 서버가 배포 후보를 검사합니다.** 서버의 `polymarket-briefing-deploy.timer`가 2분마다 `origin/main`을 폴링해 새 커밋을 별도 가상환경에서 테스트하고, 설정 검사와 DB 백업을 통과한 뒤 활성화합니다. 최초 설치, 확인, 롤백 절차는 [`systemd/README.md`](systemd/README.md)에 있습니다.

한 가지 주의할 점이 있습니다.

- `config.yaml`은 `.gitignore` 대상이라 배포로 갱신되지 않습니다. watchlist slug나 점수 기준을 바꿨다면 서버의 `config.yaml`을 `config.example.yaml`과 직접 대조해 병합해야 합니다. 특히 **설정 키를 제거하는 변경은 코드보다 서버 `config.yaml`을 먼저** 고쳐야 합니다 — 알 수 없는 키는 `ValueError`로 즉시 실패하므로 다음 실행이 통째로 죽습니다.

## GitHub Actions

저장소 Secrets에 다음 값을 등록합니다.

- `NTFY_TOPIC`
- `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`는 Telegram 사용 시에만 필요
- `OPENROUTER_API_KEY`는 AI 요약 사용 시에만 필요. 키가 없거나 호출이 실패하면 규칙 기반 요약을 사용합니다

워크플로에는 `workflow_dispatch:` 트리거만 있어 수동 실행 전용입니다. 매일 08:07 KST 정기 실행은 홈서버 systemd 타이머가 담당하며, 워크플로에 `schedule:` 트리거를 두면 홈서버 알림과 중복 발송되기 때문에 두지 않습니다.

## 요약·발송 동작

AI는 항목 제목만 JSON으로 번역합니다. 기업별 확률, 변화량, 해설, 링크와 항목 순서는 코드가 생성하고 AI가 수정할 수 없습니다. 제목 응답이 누락되거나 형식·숫자 검증을 통과하지 못하면 규칙 기반 제목을 사용합니다.

알림은 UTF-8 4,032바이트 안에서 완전한 이벤트 단위로 구성합니다. 화면에 실제 표시된 outcome만 발송 이력에 기록하며, dry-run도 같은 길이 제한을 적용합니다. 최근 발송 항목이라도 설정한 급변 기준을 넘으면 발송 감점을 적용하지 않습니다.

데이터 조회 실패와 시장 종료를 구분합니다. 모든 데이터 소스가 실패하면 알림 없이 종료 코드 1을 반환합니다. 일부만 실패하면 브리핑에 부분 조회 경고를 붙입니다. 정상적으로 조회했지만 기준을 넘는 시장이 없을 때만 “관심 시장이 없습니다”를 표시합니다.

## 상태 저장

기본 DB는 Git 체크아웃 밖의 `~/.local/state/morning-bell/briefing_state.sqlite`입니다. `POLYMARKET_BRIEFING_STATE_DIR` 또는 `XDG_STATE_HOME`으로 기본 위치를 변경할 수 있습니다. 명시적인 사용자 지정 DB 경로는 그대로 사용합니다.

기존 설정의 `state/briefing_state.sqlite`도 새 기본 위치로 해석합니다. 새 DB가 없고 기존 파일이 있으면 SQLite backup API로 최초 한 번 복사합니다. 원본은 보존하고, 새 DB가 있으면 이전 사본으로 덮어쓰지 않습니다. dry-run은 DB를 메모리에 복사해 조회하며 파일 생성·이전·발송 기록을 하지 않습니다.

배포 전 백업은 `~/.local/state/morning-bell/backups/`에 저장합니다. 수동 백업과 네트워크 없는 설정 검증:

```bash
polymarket-briefing validate-config --config config.yaml
polymarket-briefing backup-state --config config.yaml --output /safe/path/backup.sqlite
```

GitHub 수동 실행의 DB는 별도의 임시 디렉터리에 생성하고 7일짜리 artifact로 보관합니다. DB를 Git에 커밋하지 않습니다. 수동 실행과 홈서버는 발송 이력을 공유하지 않으므로, 같은 날 수동 실행하면 별도 알림이 발송될 수 있습니다.

PR 및 main push의 `CI` 워크플로는 Python 3.11/3.13에서 린트·단위/통합 테스트·예제 설정·배포 스크립트 구문을 검사합니다. 외부 API 및 알림은 통합 테스트에서 모의 처리합니다.

## 검증

```bash
ruff check .
pytest -q
polymarket-briefing run --config config.example.yaml --dry-run
```

## 안전 원칙

이 프로젝트는 공개 market data만 조회합니다. trading endpoint, private key, wallet signing, deposit/withdrawal, 주문 생성/취소 기능을 추가하지 않습니다. 모든 요약은 정보 제공 목적이며 투자 조언이 아닙니다.

