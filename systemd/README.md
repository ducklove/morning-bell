# 홈서버 배포 (systemd user units)

매일 08:07 KST 브리핑은 GitHub Actions가 아니라 **홈서버의 systemd user timer**가 실행합니다.
이 디렉터리의 파일은 참고용 예시가 아니라 **실제 운영 중인 서버(`pi-control`, `~/Works/morning-bell`)에서 그대로 가져온 것**입니다. 이전에는 버전 관리 밖에 있어서 서버가 사라지면 복구할 방법이 없었습니다.

## 구성

유닛이 두 쌍입니다.

| 유닛 | 주기 | 하는 일 |
|---|---|---|
| `polymarket-briefing.timer` → `.service` | 매일 08:07 (`Persistent=true`) | 브리핑 1회 실행 |
| `polymarket-briefing-deploy.timer` → `.service` | 2분마다 | `origin/main`을 폴링해 새 커밋이 있으면 자동 배포 |

즉 **배포는 push로 끝납니다.** `deploy.sh`가 2분 안에 받아갑니다.

`deploy.sh`의 안전장치:

- `flock`으로 중복 실행 방지
- 브리핑이 실행 중이면 건너뜀 (실행 중인 briefing 밑에서 코드를 바꾸지 않음)
- `origin/main`과 HEAD가 같으면 아무것도 안 함
- 변경이 있으면 `git reset --hard origin/main` 후 `pip install -e .`
- 기록은 `state/deploy.log`

## 파일 위치

저장소의 이 디렉터리와 서버의 실제 위치가 다릅니다.

```
systemd/deploy.sh                          -> ~/Works/morning-bell/systemd/deploy.sh (저장소 안에서 직접 실행)
systemd/polymarket-briefing*.service|timer -> ~/.config/systemd/user/
```

## 최초 설치

```bash
install -Dm644 systemd/polymarket-briefing.service        ~/.config/systemd/user/polymarket-briefing.service
install -Dm644 systemd/polymarket-briefing.timer          ~/.config/systemd/user/polymarket-briefing.timer
install -Dm644 systemd/polymarket-briefing-deploy.service ~/.config/systemd/user/polymarket-briefing-deploy.service
install -Dm644 systemd/polymarket-briefing-deploy.timer   ~/.config/systemd/user/polymarket-briefing-deploy.timer
systemctl --user daemon-reload
systemctl --user enable --now polymarket-briefing.timer polymarket-briefing-deploy.timer
loginctl enable-linger "$USER"   # 로그인 없이도 타이머가 돌게 함
```

`loginctl enable-linger`가 없으면 user timer는 로그인 전까지 동작하지 않습니다.

## 확인

```bash
systemctl --user list-timers polymarket-briefing.timer polymarket-briefing-deploy.timer
journalctl --user -u polymarket-briefing.service -n 50 --no-pager
tail -20 ~/Works/morning-bell/state/deploy.log
```

발송 없이 확인만:

```bash
cd ~/Works/morning-bell && .venv/bin/polymarket-briefing run --config config.yaml --dry-run
```

수동 1회 실행은 **실제 알림을 발송합니다**:

```bash
systemctl --user start polymarket-briefing.service
```

## config.yaml은 배포되지 않습니다

`config.yaml`은 `.gitignore` 대상이라 **`git reset --hard`로 갱신되지 않습니다.** 워치리스트나 점수 기준을 바꾸면 `config.example.yaml`만 저장소에 반영되고 서버는 예전 값을 그대로 씁니다. push 후 반드시 대조하세요.

```bash
diff -u ~/Works/morning-bell/config.yaml ~/Works/morning-bell/config.example.yaml
```

설정 키를 제거하는 변경을 배포할 때는 **코드보다 `config.yaml`을 먼저** 고쳐야 합니다. 알 수 없는 키는 `ValueError`로 즉시 실패하므로, 서버 설정에 사라진 키가 남아 있으면 다음 08:07 실행이 통째로 죽습니다.

## 롤백

deploy 타이머가 2분마다 `origin/main`으로 되돌리므로, 서버에서 `git reset`만 하면 곧 원복됩니다. 실제 롤백은 둘 중 하나입니다.

```bash
# 1) 타이머를 멈추고 서버에서 되돌리기
systemctl --user stop polymarket-briefing-deploy.timer
cd ~/Works/morning-bell && git reset --hard <직전_커밋> && .venv/bin/pip install -e . --quiet

# 2) 또는 GitHub의 main을 되돌리면 2분 내 자동 반영
```

## 주의

- `Persistent=true`라서 서버가 08:07에 꺼져 있었다면 켜진 직후 밀린 실행이 발생합니다 (실제 알림 발송).
- 타이머는 시스템 시간대를 따릅니다. `timedatectl`이 `Asia/Seoul`인지 확인하세요.
- 시크릿은 저장소가 아니라 서버의 `keys` 파일에 있습니다. 서버를 재구축하면 다시 넣어야 합니다.
