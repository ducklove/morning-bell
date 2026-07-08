import pytest

from polymarket_briefing.config import load_config


def _write_config(tmp_path, extra_yaml: str = ""):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
timezone: Asia/Seoul
watchlist_slugs: []
{extra_yaml}
""".strip(),
        encoding="utf-8",
    )
    return path


def test_load_config_defaults(tmp_path):
    cfg = load_config(_write_config(tmp_path))
    assert cfg.timezone == "Asia/Seoul"
    assert cfg.storage.retention_days == 30


def test_load_config_accepts_known_score_weight(tmp_path):
    config_path = _write_config(
        tmp_path,
        "scoring:\n  score_weights:\n    change_signal: 0.5\n",
    )
    cfg = load_config(config_path)
    assert cfg.scoring.score_weights["change_signal"] == 0.5


def test_load_config_rejects_unknown_score_weight_key(tmp_path):
    config_path = _write_config(
        tmp_path,
        "scoring:\n  score_weights:\n    volume_signl: 0.5\n",
    )
    with pytest.raises(ValueError, match="volume_signl"):
        load_config(config_path)
