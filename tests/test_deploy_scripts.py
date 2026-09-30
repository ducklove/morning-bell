from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRUNE = ROOT / "systemd" / "prune-releases.sh"
DEPLOY = ROOT / "systemd" / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")

REV_A = "a" * 40
REV_B = "b" * 40
REV_C = "c" * 40


def _release(root: Path, rev: str, stamp: str) -> Path:
    path = root / f"{rev}-{stamp}-123"
    (path / "venv" / "bin").mkdir(parents=True)
    return path


def _prune(releases: Path, *keep: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PRUNE), str(releases), *map(str, keep)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("script", [DEPLOY, PRUNE])
def test_scripts_parse(script: Path) -> None:
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_deploy_prunes_after_a_successful_switch() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    prune_at = text.index('prune-releases.sh" "$RELEASES_DIR" "$RELEASE" "$PREVIOUS_VENV"')
    assert text.index('> "$STATE_DIR/deployed-revision"') < prune_at
    assert text.rindex("trap - ERR") < prune_at


def test_keeps_current_and_previous_and_drops_the_rest(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    oldest = _release(releases, REV_A, "20260901T080000")
    previous = _release(releases, REV_B, "20260910T080000")
    failed = _release(releases, REV_C, "20260915T080000")
    current = _release(releases, REV_C, "20260920T080000")
    # The checkout's .venv symlink points into the previous release.
    link = tmp_path / ".venv"
    link.symlink_to(previous / "venv")

    result = _prune(releases, current, link.resolve())

    assert result.returncode == 0, result.stderr
    assert current.is_dir() and previous.is_dir()
    assert not oldest.exists() and not failed.exists()
    assert "pruned release" in result.stdout


def test_leaves_unrecognised_entries_alone(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    current = _release(releases, REV_A, "20260920T080000")
    stray = releases / "manual-backup"
    stray.mkdir()
    note = releases / "notes.txt"
    note.write_text("keep me", encoding="utf-8")

    assert _prune(releases, current).returncode == 0
    assert stray.is_dir() and note.is_file() and current.is_dir()


def test_previous_venv_outside_releases_is_ignored(tmp_path: Path) -> None:
    """First upgrade: the old .venv was moved aside inside the checkout."""
    releases = tmp_path / "releases"
    current = _release(releases, REV_B, "20260920T080000")
    older = _release(releases, REV_A, "20260901T080000")
    legacy = tmp_path / "repo" / ".venv-before-20260920T080000-1"
    legacy.mkdir(parents=True)

    assert _prune(releases, current, legacy).returncode == 0
    assert current.is_dir() and legacy.is_dir()
    assert not older.exists()


def test_refuses_when_nothing_to_keep_resolves(tmp_path: Path) -> None:
    releases = tmp_path / "releases"
    only = _release(releases, REV_A, "20260901T080000")

    result = _prune(releases, tmp_path / "missing", releases / f"{REV_B}-20260902T080000-1")

    assert result.returncode != 0
    assert only.is_dir()


def test_missing_releases_dir_is_a_no_op(tmp_path: Path) -> None:
    assert _prune(tmp_path / "nope", tmp_path).returncode == 0
