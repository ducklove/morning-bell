# Polymarket 아침 브리핑 — 프로젝트 검토 보고서

- 검토일: 2026-07-28
- 대상 커밋: `8bee2f8` (main, clean)
- 규모: 소스 8개 모듈 1,318줄 / 테스트 8개 파일 452줄 / 커밋 33개

---

## 0. 한 줄 요약

**뼈대는 잘 만들어져 있는데, 제품의 핵심 기능 세 개가 조용히 꺼져 있습니다.**
워치리스트가 두 달 전 종료된 시장을 가리켜 전량 폐기되고 있고, 점수의 40%를 차지하는 "24시간 급변" 신호가 사실상 항상 0이며, 한국어 번역이 영어와 뒤섞여 나옵니다. 셋 다 예외를 던지지 않고 조용히 실패하기 때문에 `pytest`(42개 통과)와 `ruff`(클린)로는 잡히지 않습니다.

---

## 1. 검증 방법

보고서의 모든 주장은 아래를 **실제로 실행해서** 확인했습니다(추정 아님).

```bash
ruff check .          # All checks passed
pytest -q             # 42 passed
polymarket-briefing run --config config.example.yaml --dry-run   # 실 API 호출
polymarket-briefing fetch-watchlist --config config.example.yaml
pytest --cov=polymarket_briefing --cov-report=term-missing
```

추가로 실 데이터 계측(이벤트 수, outcome 수, DB 증가량, 쿼리 플랜, CLOB 이력 시각, 메시지 바이트 수)과 거래·지갑 코드 부재 확인을 위한 grep 감사를 수행했습니다.

---

## 2. 종합 평가

| 영역 | 등급 | 근거 |
|---|---|---|
| 안전성 / read-only 준수 | **A** | 거래·지갑·서명·입출금 코드 0건. 아웃바운드 호스트 5개뿐 |
| 아키텍처 / 모듈 설계 | **A−** | 단일 책임 분리, 순수 함수 위주, frozen dataclass |
| 데이터 파싱 견고성 | **A−** | 4,552 outcome 정규화 중 예외 0건 |
| 테스트 | **B−** | 순수 로직 91~100%, 네트워크·오케스트레이션 24~46% |
| 핵심 기능 실동작 | **D** | 워치리스트 사망, 델타 미작동 |
| 산출물(한국어) 품질 | **D** | 영·한 혼합 문장이 기본값 |
| 운영 / 배포 | **D** | 실제 실행 경로가 저장소 밖 |
| 문서 정확성 | **C−** | README가 현재 동작과 불일치 |

**종합: C+** — 코드 품질은 좋으나 제품으로서 오늘 아침 실제로 유용한 브리핑을 보내지 못하고 있습니다.

---

## 3. 강점 (유지할 것)

1. **안전 원칙이 선언에 그치지 않고 실제로 지켜짐.** grep 감사 결과 `private_key`, `wallet`, `sign`, `deposit`, `withdraw`, 주문 생성 코드가 전무합니다. 매칭된 항목은 전부 `ORDER BY`, `_display_order` 같은 오탐이었습니다. 아웃바운드는 gamma-api / clob / ntfy / telegram / openrouter 다섯 곳뿐이고, HTTP 쓰기는 알림 POST 2곳뿐입니다. README·AGENTS.md의 read-only 선언과 코드가 정확히 일치합니다.

2. **모듈 경계가 깔끔합니다.** `client → normalize → scoring → summarize → notifier`가 단일 책임으로 나뉘고 부작용이 가장자리(cli, notifier, storage)에 몰려 있어, 핵심 로직이 네트워크 없이 테스트 가능합니다.

3. **방어적 파싱이 실전 수준입니다.** `as_list` / `as_float` / `as_bool` / `parse_datetime`가 JSON 문자열과 list를 모두 받고, `_first_float`가 `volume24hr → volume24hrClob → volume24h` 순으로 폴백합니다. 실 API에서 4,552개 outcome을 정규화하는 동안 예외가 한 건도 없었습니다. AGENTS.md의 "필드 누락/변경을 우아하게 처리"가 지켜졌습니다.

4. **네트워크 기본기가 갖춰져 있습니다.** 타임아웃 필수, 429/5xx 지수 백오프, slug endpoint 실패 시 쿼리 파라미터 폴백([polymarket_client.py:45](src/polymarket_briefing/polymarket_client.py:45)).

5. **주석이 "왜"를 설명합니다.** ntfy 헤더를 `bytes`로 넘기는 이유([notifier.py:18](src/polymarket_briefing/notifier.py:18)), CLOB이 `interval`이 있으면 `startTs`를 무시한다는 사실([polymarket_client.py:78](src/polymarket_briefing/polymarket_client.py:78)), 항목이 아니라 이벤트 수로 잘라야 Yes/No 쌍이 안 갈린다는 설명([cli.py:289](src/polymarket_briefing/cli.py:289)) — 실제로 데인 경험이 코드에 남아 있습니다.

6. **테스트가 회귀 방지에 기여하고 있습니다.** 한글 ntfy 헤더 `UnicodeEncodeError`, 가격 `0.0`이 falsy로 버려지던 버그, Yes/No 쌍 분리 버그가 각각 테스트로 고정되어 있습니다.

---

## 4. 문제점 (심각도순)

### 🔴 P0-1. 워치리스트가 조용히 전면 사망

`config.example.yaml`의 워치리스트 2개가 모두 **2026-05-31에 종료된 시장**입니다. 검증:

```
outcomes returned: 60
  which-company-has-the-best-ai-model-end-of-may | closed=True | active=True | end=2026-05-31 | p=0.0/1.0
```

60개 outcome 전부 `closed=True`라 [`_filter_closed`](src/polymarket_briefing/cli.py:209)가 전량 폐기합니다. **stderr에 아무것도 출력되지 않습니다** — `skip watchlist` 경고는 `RuntimeError`(조회 실패)일 때만 나오고, "조회는 성공했지만 전부 종료됨"은 정상 경로이기 때문입니다.

결과: plan.md의 **1순위 요구사항**이 무력화됐고, 오늘 브리핑 7개 항목 중 워치리스트 유래는 **0개**입니다. 확률도 이미 0.0/1.0으로 확정돼 정보 가치가 없습니다.

부수 발견: Gamma API는 `active=True`와 `closed=True`를 **동시에** 반환합니다. `closed`만 신뢰해야 하며, 현재 코드는 맞게 하고 있습니다.

> **수정:** 워치리스트 slug가 유효 outcome 0개를 내면 경고를 남기고, 브리핑 하단에 "워치리스트 N개 만료 — 갱신 필요"를 표시. 만료 감지는 5줄이면 됩니다.

---

### 🔴 P0-2. 한국어 번역 붕괴 — 제품의 최종 산출물

오늘 실제 출력을 그대로 옮깁니다.

```
NVIDIA가 the 세계 최대 기업 시가총액 기준 on 7월 31일까? 예 20.5%
Gadi Eizenkot가 the next Prime Minister of Israel일까? 예 51.9%
US x Iran Effective 휴전 by 7월 31 예 56.5%
해설: 현재 시장은 찬반이 팽팽한 구간로 보고 있습니다.
```

원인은 두 겹입니다.

1. [`_translate_market_phrase`](src/polymarket_briefing/summarize.py:174)가 **단어 단위 regex 치환**입니다. 사전에 있는 어구만 한국어로 바뀌고 나머지 영어가 그대로 남아 "…가 the … on 7월 31일까?" 같은 혼합 문장이 만들어집니다. 사전을 아무리 늘려도 Polymarket의 자유 형식 질문을 따라잡을 수 없는 구조입니다.

2. [정확 매칭 패턴들](src/polymarket_briefing/summarize.py:91)이 **이미 종료된 5월 시장 제목**에 맞춰져 있습니다("…end of May 2026?", "Strait of Hormuz…"). 현재 활성 시장에는 거의 매칭되지 않아 곧장 폴백 경로로 떨어집니다.

**추가로 조사(助詞) 버그:** `_stance`가 "…구간"을 반환하는데 [summarize.py:259/267](src/polymarket_briefing/summarize.py:259)이 `f"{stance}로"`로 이어 붙여 **"구간로"**가 됩니다("구간**으**로"가 맞음). 오늘 출력에 5회 등장했습니다.

> **수정:** 번역은 LLM을 **기본 경로**로 두고 규칙 기반을 폴백으로 강등하는 것이 맞습니다(아래 P1-2 항목과 연결). 조사는 받침 판정 함수 하나로 해결됩니다.

---

### 🟠 P1-3. "24시간 전 대비"가 실제로는 26시간 전 대비

[cli.py:188](src/polymarket_briefing/cli.py:188)이 26시간 윈도우를 요청하고, [cli.py:196–200](src/polymarket_briefing/cli.py:196)이 그중 **가장 오래된 점 `prices[0]`**을 "24시간 전 값"으로 씁니다. 실측 확인:

```
requested window start: 2026-07-27T11:03:30
first point time      : 2026-07-27T11:04:04   age = 26.0h
```

그런데 요약문은 "예 확률이 **24시간 전보다** X.Xpp 올랐습니다"라고 단정합니다([summarize.py:267](src/polymarket_briefing/summarize.py:267)). 26시간 전 대비 값에 24시간 라벨이 붙는 **체계적 오표기**입니다.

> **수정:** `now - 24h`에 시각이 가장 가까운 점을 고르면 됩니다. 1,179개 점이 오므로 해상도는 충분합니다.

---

### 🟠 P1-4. 점수의 40%를 차지하는 `change_signal`이 사실상 항상 0

`config.example.yaml`에서 `change_signal: 0.40` — 가장 큰 가중치입니다. 그런데 실제로는 거의 항상 0입니다.

- [cli.py:192](src/polymarket_briefing/cli.py:192): `use_clob_history = outcome.event_slug in watchlist_slugs` — **discovery 항목은 CLOB 가격 이력을 아예 조회하지 않습니다.**
- 워치리스트는 P0-1로 사망 → CLOB 경로 실행 **0회**.
- 남은 폴백은 SQLite 스냅샷인데, `state/`는 `.gitignore` 대상이고 GitHub Actions 스케줄도 제거되어(`8bee2f8`) 홈서버 로컬 DB에만 의존합니다.

오늘 dry-run 결과가 이를 그대로 보여줍니다: **7개 항목 전부 `(+X.Xpp)` 표기 없음**, 해설도 전부 델타 없는 문장입니다.

즉 랭킹은 사실상 relevance / volume / probability / deadline **네 신호(합계 0.60)로만** 결정되고 있으며, "전일 대비 급변을 잡아준다"는 제품 핵심 가치가 작동하지 않습니다.

> **수정:** `token_id`가 있는 모든 outcome에 CLOB 이력을 허용하되, 비용 관리를 위해 1차 점수 상위 N개(예: 40개)에만 적용하는 2단계 스코어링을 권장합니다.

---

### 🟠 P1-5. `max_events: 300`이 조용히 100으로 잘림

실측: `limit=300`을 요청했으나 **100개 이벤트만** 반환됐습니다. Gamma API의 페이지 상한입니다. [`list_active_events`](src/polymarket_briefing/polymarket_client.py:58)에 `offset` 파라미터가 있지만 **호출부에서 전혀 쓰이지 않아** 페이지네이션이 없습니다.

결과: discovery 풀이 설정값의 1/3이고, 거래량 상위 100개 이벤트에 고정됩니다. 이것이 오늘 결과에 **AI frontier·한국 정치 관련 시장이 0건**인 이유입니다 — 두 주제 모두 `weight: 1.0`으로 최상위 관심사인데도 말입니다.

파이프라인 실측: 100 events → 4,552 outcomes → 필터 후 1,580개.

---

### 🟠 P1-6. 실제 운영 배포 경로가 저장소에 없음

워크플로 주석([morning-briefing.yml:3–6](.github/workflows/morning-briefing.yml:3))이 `systemd/polymarket-briefing.timer`를 가리키지만, **그 파일도 디렉터리도 저장소에 없습니다**(`git ls-files`로 확인).

매일 아침 실제로 도는 것은 홈서버의 systemd 타이머인데, unit 파일·배포 스크립트·실 `config.yaml`이 전부 버전 관리 밖에 있습니다. 서버가 죽으면 재구축 절차가 없고, 변경 이력도 남지 않습니다. **현재 이 프로젝트에서 가장 큰 운영 리스크입니다.**

부수 문제: 워크플로를 수동 실행하면 `git add -f state/`로 SQLite 바이너리를 커밋해 푸시하는데, 서버가 푸시에 반응해 자동 배포한다면 서버 로컬 상태와 저장소 상태가 어긋납니다.

---

### 🟡 P2-7. ntfy 4KB 한계의 81%에 도달

오늘 메시지: **3,321 바이트** / ntfy.sh 한계 **4,096 바이트**.

초과하면 에러가 아니라 **메시지가 첨부 파일로 전환**됩니다(ntfy 공식 문서 확인). 휴대폰 알림에서 본문이 안 보이고 다운로드 카드가 뜬다는 뜻으로, 조용한 UX 붕괴입니다. 한국어는 글자당 3바이트라 항목이 한두 개만 늘거나 AI 요약이 길어지면 바로 넘습니다.

> **수정:** 발송 전 바이트 길이를 재고, 초과 시 항목 수를 줄이거나 분할 발송.

---

### 🟡 P2-8. 문서와 현실의 불일치

| 위치 | 내용 | 실제 |
|---|---|---|
| [README.md:69](README.md:69) | "워크플로는 매일 23:07 UTC에 실행됩니다" | `8bee2f8`에서 schedule 제거됨. **거짓** |
| README 시크릿 목록 | `NTFY_TOPIC`, `TELEGRAM_*` | 워크플로가 쓰는 `OPENROUTER_API_KEY` **누락** |
| README 전반 | systemd 운영 방식 | **언급 없음** |
| config.example.yaml | 워치리스트 2개 | plan.md는 4개(서울시장·largest-company 누락) |

---

### 🟡 P2-9. 죽은 설정 키 5개

grep 결과 코드 참조 **0회**: `discovery.include_active_only`, `discovery.include_closed`, `storage.snapshot_dir`, `run_time_local`, `notification.telegram.enabled`.

사용자가 `include_closed: true`로 바꿔도 아무 일이 일어나지 않습니다 — 조용한 오설정입니다. 게다가 `load_config`는 `**raw`로 넘기므로 오타 키는 불친절한 `TypeError`를 냅니다. `score_weights`만 친절한 검증([config.py:106](src/polymarket_briefing/config.py:106))을 갖고 있어 일관성이 없습니다.

모델에도 수집만 하고 쓰지 않는 필드가 있습니다: `resolution_source`, `event_id`, `market_slug`.

---

### 🟡 P2-10. 테스트 공백이 하필 위험한 곳에 집중

전체 64%인데 분포가 문제입니다.

| 모듈 | 커버리지 | 미검증 영역 |
|---|---|---|
| `polymarket_client.py` | **24%** | 재시도·백오프·slug 폴백 전부 |
| `ai_summary.py` | **26%** | `_numbers_are_grounded` 환각 방지 가드 |
| `charts.py` | 28% | 차트 생성 경로 |
| `cli.py` | 46% | `run` 오케스트레이션(51–108) |
| `config` / `storage` / `summarize` | 100 / 97 / 91% | 양호 |

`pytest-httpx`가 이미 의존성에 있는데 클라이언트 테스트에 안 쓰이고 있습니다. 특히 **환각 가드가 미검증**인 것이 위험합니다 — 이게 뚫리면 잘못된 확률이 그대로 알림으로 나갑니다.

---

### 🟢 P3 — 그 외

- **`_numbers_are_grounded`가 숫자 뒤바꿈을 못 잡음.** [ai_summary.py:135](src/polymarket_briefing/ai_summary.py:135)는 부분집합 검사만 하므로, AI가 Apple의 79.3%를 NVIDIA에 붙여도 통과합니다. 시장↔숫자 **쌍** 검증이 필요합니다.
- **스냅샷 조회에 인덱스 없음.** `outcome_snapshots`에 인덱스가 없어 47,400행 기준 `EXPLAIN QUERY PLAN`이 `SCAN` + `TEMP B-TREE`입니다. 실행당 1,580회 조회 = 약 2.2초. 지금은 감당되지만 (행수 × outcome수)로 커집니다. `CREATE INDEX ... ON outcome_snapshots(event_slug, market_id, outcome, observed_at)` 한 줄로 해결됩니다.
- **선택 로직이 한국어 UI 문자열에 결합.** [cli.py:251](src/polymarket_briefing/cli.py:251)이 `"최근 발송" in item.reasons`로 분기합니다. `reasons`는 표시용 문구인데 제어 흐름이 여기 의존하므로, 문구를 다듬으면 선택 로직이 조용히 깨집니다. Enum·플래그로 분리해야 합니다.
- **중복 방지가 1등 항목에만 의존.** [cli.py:85–93](src/polymarket_briefing/cli.py:85)이 `selected[0]`만으로 키를 만들어, 2~7위가 전부 바뀌어도 1등이 같으면 스킵하고 1등 확률이 0.1%p만 변해도 전체를 재발송합니다. 또 `selected`가 비면([cli.py:104](src/polymarket_briefing/cli.py:104)) 중복 검사도 기록도 없이 무조건 발송합니다.
- **발송 실패 시 스냅샷 유실.** `notify()`가 예외를 던지면 [cli.py:106–108](src/polymarket_briefing/cli.py:106)의 스냅샷 저장이 실행되지 않아, 발송에 실패한 날은 다음날 델타 기준선까지 사라집니다. 저장을 발송 앞으로 옮기거나 `try/finally`가 필요합니다.
- **브리핑 편집 품질.** 오늘 7개 항목 중 "Largest Company"가 2개(7월·8월), "US-Iran"이 2개(휴전·회담)로 실질 5주제입니다. `Tesla 예 0.1%`, `Aldo Rebelo 예 0.1%` 같은 정보가치 없는 후보가 노출되고, 다중 마켓 정렬이 내부 score 기준([summarize.py:52](src/polymarket_briefing/summarize.py:52))이라 **NVIDIA 20.5%가 Apple 79.3%보다 먼저** 표시됩니다. "왜 봄"은 7개 중 6개가 "관심 키워드"로 변별력이 없습니다.

---

## 5. 개선 로드맵

### 1단계 — 브리핑을 다시 "맞게" 만들기 (반나절)

1. 워치리스트 만료 감지 + 경고, 현재 slug를 활성 시장으로 교체 (P0-1)
2. 델타 기준점을 `now-24h` 최근접 점으로 변경 (P1-3)
3. 조사 버그 수정 — 받침 판정 후 `으로/로` (P0-2 일부)
4. ntfy 발송 전 바이트 길이 가드 (P2-7)
5. README의 스케줄 기술 수정 + `OPENROUTER_API_KEY` 문서화 (P2-8)

### 2단계 — 죽은 신호 복구 (1~2일)

6. CLOB 이력을 상위 N개 후보 전체로 확대 → `change_signal` 되살리기 (P1-4)
7. discovery 페이지네이션 구현 → 풀 300개 확보 (P1-5)
8. 주제 중복 억제 + 확률 하한(예: 3% 미만 후보 숨김) + 다중 마켓을 확률순 정렬 (P3)
9. 스냅샷 인덱스 추가 (P3)

### 3단계 — 운영 신뢰 (수일)

10. `systemd/` unit·타이머·배포 스크립트를 저장소에 커밋 (P1-6) ← **가장 시급한 운영 항목**
11. `pytest-httpx`로 클라이언트 재시도·폴백 테스트, 환각 가드 테스트 추가 (P2-10)
12. 죽은 설정 키 제거 또는 구현, 알 수 없는 키에 친절한 오류 (P2-9)
13. `reasons` 문자열 결합을 Enum으로 분리 (P3)
14. 스냅샷 저장을 발송 실패와 분리 (P3)

### 4단계 — 산출물 품질

15. LLM 번역을 기본 경로로 승격, 규칙 기반은 폴백으로 (P0-2)
16. 환각 가드를 시장↔숫자 쌍 검증으로 강화 (P3)

---

## 6. 향후 추가 기능 제안

**높은 가치 / 낮은 비용**

- **워치리스트 자동 롤오버** — 이번 사고의 근본 해결책. 시장이 종료되면 같은 주제의 후속 시장(예: "end of May" → "end of August")을 슬러그 패턴이나 Gamma 태그로 찾아 자동 승계하고, 승계 결과를 브리핑에 한 줄로 알립니다.
- **급변 전용 인트라데이 알림** — 아침 브리핑과 별개로, 임계치(예: 8pp) 초과 시에만 조용히 푸시. plan.md §21의 "급변 only 모드"를 알림 채널로 확장한 형태입니다.
- **resolution criteria 요약** — `resolution_source`를 이미 수집하고 있으나 쓰지 않습니다. "무엇으로 판정되는가"는 예측시장 브리핑에서 확률만큼 중요합니다.
- **"왜 봄" 고도화** — 지금은 6/7이 "관심 키워드"입니다. 어떤 키워드가·어느 프로필에서 걸렸는지, 델타/거래량 중 무엇이 결정적이었는지를 보여주면 신뢰도가 올라갑니다.

**중간 규모**

- **주간 리뷰** — 한 주간 확률 변화 폭이 컸던 시장, 새로 등장한 시장, 해소된 시장을 일요일에 정리.
- **캘리브레이션 추적** — 종료된 시장의 최종 결과와 브리핑 시점 확률을 대조해 "시장이 얼마나 맞았나"를 누적. 스냅샷 DB가 이미 원재료를 갖고 있어 추가 수집이 필요 없습니다.
- **Gamma 태그 기반 discovery** — 키워드 문자열 매칭 대신 API의 카테고리/태그를 쓰면 P1-5의 커버리지 문제를 구조적으로 완화합니다.
- **개인화 피드백 루프** — Telegram 인라인 버튼으로 "관심/무관심"을 받아 키워드 가중치를 조정.

**인프라**

- 알림 채널 다중화(ntfy + Telegram 동시), 발송 실패 시 대체 채널 폴백
- 스냅샷을 외부 DB(Supabase / Cloudflare D1)로 이전해 홈서버 단일 장애점 제거
- `mypy` 도입 — AGENTS.md가 "typed"를 요구하는데 현재 타입 체커가 없고 `_fetch_all(client, cfg)` 등에 어노테이션이 빠져 있습니다

---

## 7. 맺음

이 프로젝트의 문제는 코드 실력이 아니라 **관측 가능성(observability)** 입니다. 워치리스트 사망, 델타 0, 페이지 상한 절삭 — 세 가지 모두 예외 없이 조용히 실패했고, 그래서 테스트와 린트를 모두 통과한 채로 두 달을 지나왔습니다.

가장 값싸고 효과가 큰 한 가지를 고른다면, **브리핑 하단에 실행 자기진단 한 줄을 붙이는 것**입니다.

```
진단: 워치리스트 2/2 만료 · 델타 0/7 계산됨 · discovery 100/300 이벤트
```

이 한 줄이 있었다면 위 P0·P1 문제 대부분이 첫날 아침에 드러났을 것입니다.
