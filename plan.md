# Codex 작업 요청서: Polymarket 아침 브리핑 알림봇

작성일: 2026-04-27  
기준 시간대: Asia/Seoul  
목표: 매일 아침 Polymarket 시장을 조회해, 관심도 높은 예측시장 변화를 한국어로 요약하고 휴대폰 알림으로 전송하는 read-only 브리핑 봇을 구현한다.

---

## 0. Codex에게 바로 전달할 요청문

아래 요구사항에 맞춰 Python 프로젝트를 새로 만들어 주세요. 목표는 **Polymarket 아침 브리핑 알림봇**입니다. 이 봇은 거래를 하지 않고, 공개 시장 데이터만 읽어서 매일 아침 한국어 요약 알림을 보냅니다.

반드시 구현할 것:

1. Polymarket Gamma API로 지정 watchlist 이벤트를 slug 기준으로 조회한다.
2. Polymarket 활성 이벤트를 훑어 관심 키워드와 거래량/확률 변화 기준으로 새 관심 시장을 발굴한다.
3. 각 이벤트/마켓의 outcome, probability, volume, liquidity, end date, URL을 정규화한다.
4. 이전 실행 스냅샷과 비교해 24시간 확률 변화량을 계산한다.
5. 관심도 점수를 계산해 상위 3~7개 항목을 한국어로 요약한다.
6. ntfy를 기본 알림 채널로 구현하고, Telegram은 선택 구현한다.
7. 로컬 실행, dry-run, GitHub Actions 스케줄 실행을 모두 지원한다.
8. 테스트, README, config.example.yaml, AGENTS.md, GitHub Actions workflow를 포함한다.
9. 민감정보는 환경변수/GitHub Secrets만 사용하고, 저장소에 절대 커밋하지 않는다.
10. 자동 매매, 주문, 지갑, 포지션 관리 기능은 구현하지 않는다.

---

## 1. 배경과 데이터 소스

Polymarket의 market data는 공개 REST endpoint로 조회할 수 있다. 공식 문서 기준으로 Gamma API와 Data API는 인증이 필요 없고, CLOB API도 orderbook/prices 등 읽기용 public endpoint가 있다. 거래 관련 endpoint는 인증이 필요하므로 이 프로젝트에서는 사용하지 않는다.[^polymarket-public]

Polymarket의 이벤트와 마켓 구조는 `event -> markets -> outcomes/outcomePrices` 형태이며, `outcomes`와 `outcomePrices`는 1:1로 대응한다. 예를 들어 `Yes` 가격이 `0.20`이면 20% implied probability로 해석한다.[^polymarket-model]

특정 이벤트는 Polymarket URL의 `/event/{slug}`에서 slug를 추출해 조회할 수 있다. 공식 문서의 slug endpoint는 `GET https://gamma-api.polymarket.com/events/slug/{slug}`이다.[^polymarket-slug]

가격 이력은 CLOB의 `GET /prices-history`를 사용할 수 있으며, `market`, `startTs`, `endTs`, `interval` 등의 query parameter를 받는다.[^polymarket-history]

알림 채널은 ntfy를 기본으로 한다. ntfy는 HTTP PUT/POST로 topic에 메시지를 publish할 수 있고, topic은 사실상 비밀번호 역할을 하므로 추측하기 어려운 값을 써야 한다.[^ntfy] Telegram Bot API는 HTTP 기반 bot interface이며 `sendMessage`로 텍스트 메시지를 보낼 수 있으므로 선택 알림 채널로 둔다.[^telegram]

스케줄링은 로컬 cron/systemd timer 또는 GitHub Actions를 지원한다. GitHub Actions의 `schedule` event는 cron 문법으로 동작하며, 공식 문서 기준 scheduled workflow는 기본적으로 UTC에서 실행되고 timezone도 지정할 수 있다. 또한 정각 부하 시간에는 지연될 수 있으므로 08:00 정각 대신 08:07처럼 살짝 비켜서 실행하도록 한다.[^github-schedule]

Codex는 코드를 읽고 수정하고 실행할 수 있는 OpenAI coding agent이며, cloud 환경에서 작업하고 GitHub repo에 PR을 만들 수 있다. Codex 공식 best practice는 충분한 작업 맥락, 지속 지침용 `AGENTS.md`, 검증 방법을 함께 제공하는 방식을 권한다.[^codex-web][^codex-best]

---

## 2. 제품 목표

### 2.1 핵심 목표

매일 아침 08:07 KST에 다음 정보를 한국어로 요약해 휴대폰 알림으로 보낸다.

- watchlist 이벤트의 현재 확률과 주요 outcome
- 전일 대비 확률 변화가 큰 outcome
- 거래량/유동성이 큰 관심 시장
- AI, 한국 정치, 지정학/물류, 빅테크/시총 관련 신규 또는 급변 시장
- 정산일이 가까워진 관심 시장

### 2.2 비목표

- 자동 매매 금지
- 주문 생성/취소 금지
- 지갑, private key, wallet address 기반 포지션 관리 금지
- 투자 조언 문구 금지
- 사용자의 Polymarket 계정 로그인 금지
- 비공개 API나 scraping 의존 금지

문구는 “정보 요약”이어야 한다. 예: “이 시장은 24시간 동안 +7.2pp 상승했습니다.”는 가능하지만, “매수하세요”는 금지한다.

---

## 3. 초기 watchlist

다음 slug를 기본 watchlist로 둔다.

```yaml
watchlist_slugs:
  - which-company-has-the-best-ai-model-end-of-may
  - strait-of-hormuz-traffic-returns-to-normal-by-end-of-may
  - 2026-seoul-mayoral-election-winner
  - largest-company-end-of-december-2026
```

원본 URL:

```text
https://polymarket.com/ko/event/which-company-has-the-best-ai-model-end-of-may
https://polymarket.com/ko/event/strait-of-hormuz-traffic-returns-to-normal-by-end-of-may
https://polymarket.com/ko/event/2026-seoul-mayoral-election-winner
https://polymarket.com/ko/event/largest-company-end-of-december-2026
```

---

## 4. 관심도 프로필

사용자는 다음 주제에 높은 관심을 가진다고 가정한다.

1. Frontier AI 모델 경쟁
   - OpenAI, Anthropic, Google, Gemini, Claude, xAI, Grok, Chatbot Arena, LLM, AI model
2. 한국 정치
   - Seoul, Korea, mayoral election, presidential election, Democratic Party, People Power Party, major Korean candidate names
3. 지정학과 물류 리스크
   - Strait of Hormuz, Iran, Israel, shipping, oil, tanker, blockade, war, ceasefire, Red Sea
4. 빅테크/시총/AI 인프라
   - NVIDIA, Apple, Microsoft, Alphabet, Meta, Amazon, Tesla, SpaceX, market cap, largest company, GPU, datacenter

추후 config에서 키워드를 쉽게 추가/삭제할 수 있어야 한다.

---

## 5. 권장 기술 스택

- Python 3.11+
- `httpx` 또는 `requests`
- `pydantic` 또는 `dataclasses` for normalized models
- `PyYAML` for config
- `typer` for CLI
- `sqlite3` standard library or JSON snapshot storage
- `pytest` for tests
- `ruff` for linting
- `mypy` optional
- GitHub Actions for scheduled execution

LLM API 호출은 MVP에서 제외한다. 한국어 요약은 deterministic template 기반으로 구현한다. 추후 필요하면 LLM summarizer를 optional module로 추가한다.

---

## 6. 프로젝트 구조

```text
polymarket-morning-briefing/
  AGENTS.md
  README.md
  pyproject.toml
  config.example.yaml
  .env.example
  .gitignore
  src/
    polymarket_briefing/
      __init__.py
      cli.py
      config.py
      polymarket_client.py
      models.py
      normalize.py
      scoring.py
      storage.py
      summarize.py
      notifier.py
      utils.py
  tests/
    test_normalize.py
    test_scoring.py
    test_storage.py
    test_summarize.py
    test_notifier.py
  .github/
    workflows/
      morning-briefing.yml
```

---

## 7. 설정 파일 예시

`config.example.yaml`:

```yaml
timezone: Asia/Seoul
run_time_local: "08:07"

polymarket:
  gamma_base_url: "https://gamma-api.polymarket.com"
  clob_base_url: "https://clob.polymarket.com"
  request_timeout_seconds: 20
  max_retries: 3
  backoff_seconds: 1.5

watchlist_slugs:
  - which-company-has-the-best-ai-model-end-of-may
  - strait-of-hormuz-traffic-returns-to-normal-by-end-of-may
  - 2026-seoul-mayoral-election-winner
  - largest-company-end-of-december-2026

discovery:
  enabled: true
  max_events: 150
  include_active_only: true
  include_closed: false
  min_volume_24h: 5000
  keywords:
    ai_frontier:
      weight: 1.0
      terms:
        - OpenAI
        - Anthropic
        - Google
        - Gemini
        - Claude
        - xAI
        - Grok
        - Chatbot Arena
        - AI model
        - LLM
    korea_politics:
      weight: 1.0
      terms:
        - Seoul
        - Korea
        - mayor
        - election
        - presidential
        - Democratic Party
        - People Power Party
    geopolitics_logistics:
      weight: 0.9
      terms:
        - Hormuz
        - Iran
        - Israel
        - shipping
        - oil
        - tanker
        - blockade
        - ceasefire
    bigtech_marketcap:
      weight: 0.9
      terms:
        - NVIDIA
        - Apple
        - Microsoft
        - Alphabet
        - Meta
        - Amazon
        - Tesla
        - SpaceX
        - market cap
        - largest company
        - GPU

scoring:
  min_score_to_notify: 35
  max_items: 7
  probability_change_alert_pp: 3.0
  score_weights:
    change_signal: 0.45
    relevance_signal: 0.25
    volume_signal: 0.15
    deadline_signal: 0.10
    liquidity_signal: 0.05

notification:
  provider: ntfy
  dry_run_default: false
  ntfy:
    topic_env: NTFY_TOPIC
    title: "Polymarket 아침 브리핑"
    priority: 3
  telegram:
    enabled: false
    bot_token_env: TELEGRAM_BOT_TOKEN
    chat_id_env: TELEGRAM_CHAT_ID

storage:
  path: "state/briefing_state.sqlite"
  snapshot_dir: "state/snapshots"
```

---

## 8. Polymarket client 요구사항

### 8.1 함수

```python
class PolymarketClient:
    def get_event_by_slug(self, slug: str) -> dict: ...
    def list_active_events(self, limit: int = 100, offset: int = 0) -> list[dict]: ...
    def get_price_history(self, token_id: str, start_ts: int, end_ts: int, interval: str = "1d") -> dict: ...
```

### 8.2 Endpoint

1. Watchlist 조회

```text
GET https://gamma-api.polymarket.com/events/slug/{slug}
```

Fallback도 구현한다.

```text
GET https://gamma-api.polymarket.com/events?slug={slug}
```

2. Discovery 조회

```text
GET https://gamma-api.polymarket.com/events?active=true&closed=false&limit={limit}&offset={offset}
```

가능하면 거래량순 정렬 parameter를 사용하되, endpoint가 parameter를 거부할 경우 기본 조회 후 로컬에서 `volume24hr`, `volume`, `liquidity` 기준으로 정렬한다.

3. 가격 이력 조회

```text
GET https://clob.polymarket.com/prices-history?market={token_id}&startTs={start_ts}&endTs={end_ts}&interval=1d
```

### 8.3 견고성

- HTTP timeout 필수
- 429/5xx에 대해 exponential backoff
- JSON parse 실패 시 해당 이벤트만 skip하고 전체 실행은 계속
- 누락 필드는 `None` 허용
- API schema가 바뀌어도 테스트 fixture로 빠르게 감지

---

## 9. 정규화 모델

`models.py`에 다음 모델을 둔다.

```python
@dataclass(frozen=True)
class NormalizedOutcome:
    event_id: str | None
    event_slug: str
    event_title: str
    market_id: str | None
    market_slug: str | None
    market_question: str
    outcome: str
    probability: float | None  # 0.0 ~ 1.0
    token_id: str | None
    volume: float | None
    volume_24h: float | None
    liquidity: float | None
    end_date: datetime | None
    active: bool | None
    closed: bool | None
    resolution_source: str | None
    url: str
```

정규화 규칙:

- `outcomes`, `outcomePrices`, `clobTokenIds`는 list 또는 JSON string 모두 처리한다.
- `outcomes[i]`와 `outcomePrices[i]`를 1:1 매핑한다.
- 확률은 float로 저장한다. 표시할 때는 `%`와 `pp` 단위로 변환한다.
- multi-market event의 경우 모든 market/outcome을 펼쳐서 list로 만든다.
- `url`은 `https://polymarket.com/event/{event_slug}`로 생성한다.

---

## 10. 상태 저장과 변화량 계산

### 10.1 MVP 저장 방식

SQLite를 기본으로 한다.

Table: `outcome_snapshots`

```sql
CREATE TABLE IF NOT EXISTS outcome_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  event_slug TEXT NOT NULL,
  market_id TEXT,
  market_question TEXT NOT NULL,
  outcome TEXT NOT NULL,
  probability REAL,
  volume REAL,
  volume_24h REAL,
  liquidity REAL,
  url TEXT NOT NULL
);
```

Table: `sent_notifications`

```sql
CREATE TABLE IF NOT EXISTS sent_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sent_at TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL
);
```

### 10.2 변화량 계산

- 우선순위 1: CLOB token_id가 있으면 `/prices-history`에서 24h 전 가격과 현재 가격을 비교한다.
- 우선순위 2: token_id가 없거나 CLOB 이력이 실패하면 SQLite의 최근 20~30시간 내 snapshot과 비교한다.
- 변화량은 percentage point로 표시한다.

예:

```text
현재 49.0%, 24h 전 42.5% -> +6.5pp
```

### 10.3 중복 방지

`dedupe_key` 예시:

```text
{date}:{event_slug}:{market_id}:{outcome}:{rounded_probability}:{rounded_delta_pp}
```

동일 실행 또는 동일 날짜에 같은 내용이 반복 발송되지 않도록 한다.

---

## 11. 관심도 점수

각 outcome별 score를 0~100으로 계산한다.

```python
score = (
    45 * change_signal
  + 25 * relevance_signal
  + 15 * volume_signal
  + 10 * deadline_signal
  +  5 * liquidity_signal
)
```

### 11.1 change_signal

```python
change_signal = min(abs(delta_24h_pp) / 10.0, 1.0)
```

24시간 변화가 10pp 이상이면 1.0.

### 11.2 relevance_signal

- title, question, description, category, subcategory에서 관심 키워드 검색
- 카테고리별 weight 반영
- watchlist slug는 최소 relevance 0.8 부여

### 11.3 volume_signal

```python
volume_signal = log1p(volume_24h or volume) / log1p(max_volume_seen)
```

### 11.4 deadline_signal

- end_date가 7일 이내: 1.0
- 30일 이내: 0.6
- 90일 이내: 0.3
- 그 외: 0.1
- end_date 없음: 0.0

### 11.5 liquidity_signal

volume과 동일하게 log normalize.

---

## 12. 요약 포맷

알림은 짧고 읽기 쉬워야 한다.

예시:

```text
[Polymarket 아침 브리핑 | 2026-04-27]

1) AI 모델 왕좌전
Anthropic 49.0% (+6.5pp), Google 34.0% (-4.1pp), OpenAI 16.2% (-1.8pp)
왜 봄: watchlist + AI frontier 모델 경쟁 + 24h 급변
링크: https://polymarket.com/event/which-company-has-the-best-ai-model-end-of-may

2) 호르무즈 해협 정상화
Yes 38.0% (-3.2pp)
왜 봄: 지정학/물류 리스크 + 거래량 큼
링크: https://polymarket.com/event/strait-of-hormuz-traffic-returns-to-normal-by-end-of-may

꼬리표: 정보 요약이며 투자 조언이 아닙니다.
```

출력 규칙:

- 최대 7개 항목
- 항목당 2~4줄
- 변화량이 있는 경우 `(+6.5pp)` 표기
- 변화량이 없으면 현재 확률만 표기
- 확률 없는 항목은 volume/liquidity 중심으로 표기
- 모든 항목에 URL 포함
- 마지막에 “정보 요약이며 투자 조언이 아닙니다.” 포함

---

## 13. 알림 구현

### 13.1 ntfy 기본 구현

```python
def send_ntfy(topic: str, title: str, message: str, priority: int = 3) -> None:
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title,
        "Priority": str(priority),
    }
    response = httpx.post(url, content=message.encode("utf-8"), headers=headers, timeout=20)
    response.raise_for_status()
```

환경변수:

```text
NTFY_TOPIC=<hard-to-guess-topic>
```

### 13.2 Telegram 선택 구현

```python
def send_telegram(bot_token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    response = httpx.post(url, json=payload, timeout=20)
    response.raise_for_status()
```

환경변수:

```text
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_CHAT_ID=<chat-id>
```

---

## 14. CLI 요구사항

`typer` 기반 CLI를 만든다.

```bash
polymarket-briefing run --config config.yaml
polymarket-briefing run --config config.yaml --dry-run
polymarket-briefing fetch-watchlist --config config.yaml
polymarket-briefing discover --config config.yaml
polymarket-briefing test-notify --config config.yaml
```

동작:

- `run`: fetch -> normalize -> compare -> score -> summarize -> notify -> save snapshot
- `--dry-run`: 알림 발송 없이 stdout에 요약만 출력
- `fetch-watchlist`: watchlist API 조회와 정규화 결과 출력
- `discover`: 활성 이벤트 discovery 결과와 score 출력
- `test-notify`: “테스트 알림입니다” 전송

---

## 15. GitHub Actions workflow

`.github/workflows/morning-briefing.yml`:

```yaml
name: Polymarket Morning Briefing

on:
  workflow_dispatch:
  schedule:
    - cron: "7 8 * * *"
      timezone: "Asia/Seoul"

jobs:
  briefing:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Checkout
        uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e .

      - name: Run briefing
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          polymarket-briefing run --config config.yaml

      - name: Persist state snapshot
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state/ || true
          git commit -m "Update Polymarket briefing state" || echo "No state changes"
          git push || true
```

주의:

- 저장소가 public이면 state 파일에는 민감정보가 없어야 한다.
- topic, token 등은 반드시 GitHub Secrets로만 관리한다.
- GitHub Actions schedule이 부하로 지연될 수 있으므로 정각이 아닌 08:07을 사용한다.
- timezone key가 실행 환경에서 지원되지 않는 경우, fallback으로 UTC 기준 `cron: "7 23 * * *"`를 사용한다. 이는 KST 08:07에 해당한다.

---

## 16. README에 포함할 내용

README는 다음 항목을 반드시 포함한다.

1. 프로젝트 설명
2. 설치 방법
3. `config.yaml` 만드는 방법
4. ntfy 앱 설치 및 topic 설정 방법
5. Telegram 선택 설정 방법
6. 로컬 dry-run 방법
7. GitHub Secrets 설정 방법
8. GitHub Actions 스케줄 사용 방법
9. 상태 저장 방식 설명
10. 투자 조언 아님 / read-only / no trading 명시

---

## 17. AGENTS.md 내용

`AGENTS.md`는 Codex가 이후 작업에서도 일관되게 따를 지침이다.

```markdown
# AGENTS.md

## Project purpose
This project is a read-only Polymarket morning briefing bot. It summarizes public market data and sends notifications. It must not place trades, manage wallets, or provide investment advice.

## Engineering rules
- Keep the code typed and testable.
- Do not commit secrets.
- Prefer deterministic summaries over LLM calls for MVP.
- Handle missing/changed API fields gracefully.
- Any network code must have timeout and retry behavior.
- Keep notifications short and Korean-first.

## Validation
Before finalizing changes, run:

```bash
ruff check .
pytest -q
polymarket-briefing run --config config.example.yaml --dry-run
```

## Safety
Never add order placement, wallet signing, deposit, withdrawal, or credential handling for Polymarket trading.
```

---

## 18. 테스트 요구사항

### 18.1 정규화 테스트

- `outcomes`가 JSON string일 때 parse 가능
- `outcomes`가 list일 때 parse 가능
- `outcomePrices` 누락 시 crash 없음
- multi-market event를 여러 outcome으로 펼침
- `clobTokenIds`와 outcome 매핑

### 18.2 scoring 테스트

- watchlist는 relevance 기본값을 받음
- 10pp 이상 변화는 `change_signal = 1.0`
- end_date 7일 이내는 deadline_signal 1.0
- volume normalize가 0~1 범위를 넘지 않음

### 18.3 storage 테스트

- snapshot insert/read
- 24h 이전 snapshot lookup
- 중복 notification key 방지

### 18.4 summarize 테스트

- 한국어 header 포함
- URL 포함
- 투자 조언 아님 문구 포함
- max_items 준수

### 18.5 notifier 테스트

- ntfy HTTP request mock
- Telegram HTTP request mock
- dry-run은 network call 없음

---

## 19. 완료 기준

작업이 끝났다고 판단하는 기준:

1. `pip install -e .` 성공
2. `pytest -q` 성공
3. `ruff check .` 성공
4. `polymarket-briefing run --config config.example.yaml --dry-run`이 샘플 요약을 출력
5. 실제 `config.yaml`과 `NTFY_TOPIC`을 설정하면 ntfy 알림 발송 성공
6. watchlist 4개 이벤트가 정상 조회됨
7. API 오류가 일부 발생해도 전체 실행이 실패하지 않음
8. 이전 snapshot이 있으면 변화량 pp가 표시됨
9. README만 보고 GitHub Actions 배포가 가능함
10. 코드 어디에도 trading endpoint, wallet signing, private key 처리가 없음

---

## 20. 구현 순서

1. 프로젝트 scaffold 생성
2. config loader 구현
3. PolymarketClient 구현
4. 정규화 모델과 parser 구현
5. SQLite storage 구현
6. 변화량 계산 구현
7. scoring 구현
8. 한국어 summary template 구현
9. ntfy notifier 구현
10. Telegram notifier 선택 구현
11. CLI 구현
12. tests 작성
13. README/AGENTS.md 작성
14. GitHub Actions workflow 작성
15. dry-run 결과 예시 추가

---

## 21. 추가 개선 아이디어

MVP 이후에 다음 기능을 붙일 수 있다.

- 관심 키워드 자동 업데이트
- 주간 리포트 생성
- 중요도 낮은 알림 무음 처리
- “전일 대비 급변 only” 모드
- Polymarket category/tag 기반 discovery 강화
- 특정 이벤트의 resolution criteria 요약
- 시장별 source of truth 링크 표시
- Telegram inline button 추가
- SQLite 대신 Supabase/Cloudflare D1 같은 외부 DB 사용

---

## 22. 출처

[^polymarket-public]: Polymarket Documentation, “API Reference Introduction,” Gamma API/Data API are public and CLOB has public read endpoints; trading endpoints require authentication. https://docs.polymarket.com/api-reference/introduction
[^polymarket-model]: Polymarket Documentation, “Market Data Overview,” event/market data model and `outcomes` ↔ `outcomePrices` implied probability mapping. https://docs.polymarket.com/market-data/overview
[^polymarket-slug]: Polymarket Documentation, “Get event by slug,” `GET /events/slug/{slug}`. https://docs.polymarket.com/api-reference/events/get-event-by-slug
[^polymarket-history]: Polymarket Documentation, “Get prices history,” `GET /prices-history` query parameters. https://docs.polymarket.com/api-reference/markets/get-prices-history
[^ntfy]: ntfy Documentation, “Publishing,” HTTP PUT/POST publish and topic secrecy guidance. https://docs.ntfy.sh/publish/
[^telegram]: Telegram Bot API, HTTP-based bot interface and `sendMessage`. https://core.telegram.org/bots/api
[^github-schedule]: GitHub Docs, “Events that trigger workflows: schedule,” cron schedule behavior, UTC/timezone, and possible delay at high-load times. https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
[^codex-web]: OpenAI Developers, “Codex web,” Codex can read, edit, run code, work in cloud, and create pull requests. https://developers.openai.com/codex/cloud
[^codex-best]: OpenAI Developers, “Codex best practices,” recommends task context, `AGENTS.md`, validation, skills, and automations. https://developers.openai.com/codex/learn/best-practices
