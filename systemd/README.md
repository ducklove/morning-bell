# 홈서버 배포

매일 08:07 Asia/Seoul에 `polymarket-briefing.timer`가 브리핑을 실행합니다. `polymarket-briefing-deploy.timer`는 2분마다 origin/main을 확인합니다. 저장소 위치는 `~/Works/morning-bell`이며, 서버의 `config.yaml`과 `keys`는 배포에서 보존합니다.

## 배포 절차

1. 별도 release 디렉터리에 새 커밋을 풀고 가상환경을 만듭니다.
2. 린트·전체 테스트·운영 설정 검사를 수행합니다. 실패하면 실행 중인 버전은 유지합니다.
3. 기존 DB를 Git 밖으로 이전하고 SQLite backup API로 배포 전 백업을 만듭니다.
4. 체크아웃과 `.venv` 심볼릭 링크를 검증한 버전으로 전환합니다.
5. systemd unit을 갱신하고 `daemon-reload`합니다. 활성화 실패 시 코드·가상환경·unit을 복원합니다.
6. 전환에 성공하면 `prune-releases.sh`가 현재 release와 직전 release(롤백 대상)만 남기고 나머지 release 디렉터리(테스트에 실패한 빌드 포함)를 지웁니다. 정리 실패는 배포를 실패시키지 않습니다.

브리핑과 배포는 같은 `~/.local/state/morning-bell/run.lock`을 사용합니다. 브리핑 중에는 배포를 건너뛰고, 배포 중 시작된 브리핑은 최대 10분 기다립니다. 배포 과정에서 실제 브리핑을 발송하지 않습니다.

## 경로

- 운영 DB: `~/.local/state/morning-bell/briefing_state.sqlite`
- 배포 전 백업: `~/.local/state/morning-bell/backups/`
- 배포 로그·활성 revision: `~/.local/state/morning-bell/deploy.log`, `deployed-revision`
- 설치된 release: `~/.local/share/morning-bell/releases/` (현재 + 직전 1개만 유지)
- systemd unit: `~/.config/systemd/user/`

기존 `state/briefing_state.sqlite`는 최초 한 번 복사하고 원본을 남깁니다. dry-run은 이전 작업을 수행하지 않습니다. 사용자 지정 DB가 Git 체크아웃 안에 있으면 배포를 중단하므로 먼저 외부 경로로 이전하세요.

## 최초 설치 또는 이전 배포 방식에서 업그레이드

README의 설치 절차대로 `.venv`, `config.yaml`, `keys`를 준비합니다. 기존 배포 타이머를 멈추고 새 배포 스크립트를 임시 파일에서 한 번 실행합니다. `main`에 검증한 변경이 올라간 뒤 실행하세요.

```bash
systemctl --user stop polymarket-briefing-deploy.timer
cd ~/Works/morning-bell
git fetch origin main
git show origin/main:systemd/deploy.sh > /tmp/morning-bell-deploy.sh
bash /tmp/morning-bell-deploy.sh
systemctl --user enable --now polymarket-briefing.timer polymarket-briefing-deploy.timer
loginctl enable-linger "$USER"
```

스크립트는 Linux의 `flock`, `timeout`, GNU `mv`를 사용합니다. Python 3.11 이상과 `venv` 지원이 필요합니다. 이후에는 `main` push를 자동 감지합니다. PR CI를 통과한 코드를 병합하세요. 서버에서도 동일 테스트를 다시 수행합니다.

## 확인

```bash
systemctl --user list-timers polymarket-briefing.timer polymarket-briefing-deploy.timer
journalctl --user -u polymarket-briefing.service -n 50 --no-pager
tail -30 ~/.local/state/morning-bell/deploy.log
cat ~/.local/state/morning-bell/deployed-revision
cd ~/Works/morning-bell
.venv/bin/polymarket-briefing run --config config.yaml --dry-run
```

API 접근이 차단되거나 모든 소스가 실패하면 dry-run도 종료 코드 1을 반환합니다. 일부 소스만 실패하면 부분 조회 경고가 출력됩니다. 실제 전송 검사는 별도 수동 실행으로 알림을 발송하므로 배포 확인에는 dry-run을 사용합니다.

## 설정 변경과 롤백

`config.yaml`은 자동 교체하지 않습니다. 새 설정은 `config.example.yaml`과 비교하고 `validate-config`로 검사하세요. 기존 기본 DB 경로는 자동 호환됩니다. unit 파일은 매 배포 때 갱신됩니다.

장애 시 먼저 배포 타이머를 멈추세요. 이전 정상 코드를 `git revert`로 main에 복구하고 타이머를 다시 켜면 검증 후 새 release로 배포됩니다. 즉시 수동 복구가 필요하면 deploy.log의 이전 release 경로로 `.venv` 링크와 해당 커밋을 함께 복구한 뒤 설정을 검증하세요. DB는 코드 롤백과 별도로 보존하며, 백업 복원은 필요할 때만 수행합니다.

`Persistent=true`이므로 예정 시각에 서버가 꺼져 있었다면 다음 기동 때 브리핑이 실행될 수 있습니다. 비밀값은 서버의 `keys` 파일에서만 관리합니다.
