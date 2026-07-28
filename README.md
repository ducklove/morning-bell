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

**배포는 `main`에 push하면 끝납니다.** 서버의 `polymarket-briefing-deploy.timer`가 2분마다 `origin/main`을 폴링해 새 커밋을 자동으로 받아갑니다. 최초 설치, 확인, 롤백 절차는 [`systemd/README.md`](systemd/README.md)에 있습니다.

한 가지 주의할 점이 있습니다.

- `config.yaml`은 `.gitignore` 대상이라 배포로 갱신되지 않습니다. watchlist slug나 점수 기준을 바꿨다면 서버의 `config.yaml`을 `config.example.yaml`과 직접 대조해 병합해야 합니다. 특히 **설정 키를 제거하는 변경은 코드보다 서버 `config.yaml`을 먼저** 고쳐야 합니다 — 알 수 없는 키는 `ValueError`로 즉시 실패하므로 다음 실행이 통째로 죽습니다.

## GitHub Actions

저장소 Secrets에 다음 값을 등록합니다.

- `NTFY_TOPIC`
- `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`는 Telegram 사용 시에만 필요
- `OPENROUTER_API_KEY`는 AI 요약 사용 시에만 필요. 워크플로는 `--ai-summary`로 실행하므로 수동 실행에는 필수입니다

워크플로에는 `workflow_dispatch:` 트리거만 있어 수동 실행 전용입니다. 매일 08:07 KST 정기 실행은 홈서버 systemd 타이머가 담당하며, 워크플로에 `schedule:` 트리거를 두면 홈서버 알림과 중복 발송되기 때문에 두지 않습니다.

## 상태 저장

기본 DB는 `state/briefing_state.sqlite`입니다. `outcome_snapshots`에 공개 시장 스냅샷만 저장하고, `sent_notifications`로 같은 날짜의 중복 발송을 줄입니다. topic, token, 개인키 같은 민감정보는 저장하지 않습니다.

`state/`는 `.gitignore` 대상이라 평소에는 커밋되지 않습니다. 워크플로의 `Persist state snapshot` 단계가 `git add -f`로 스냅샷을 강제 커밋하지만, 이는 수동 실행이 있을 때만 일어납니다. 매일 도는 정기 경로에서는 24시간 전 확률 변화량 기준값을 홈서버의 로컬 SQLite 파일에서 읽습니다.

## 검증

```bash
ruff check .
pytest -q
polymarket-briefing run --config config.example.yaml --dry-run
```

## 안전 원칙

이 프로젝트는 공개 market data만 조회합니다. trading endpoint, private key, wallet signing, deposit/withdrawal, 주문 생성/취소 기능을 추가하지 않습니다. 모든 요약은 정보 제공 목적이며 투자 조언이 아닙니다.

