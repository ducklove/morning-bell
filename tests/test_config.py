from pathlib import Path

import pytest
import yaml

from polymarket_briefing.config import load_config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


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


def test_load_config_new_defaults(tmp_path):
    cfg = load_config(_write_config(tmp_path))
    assert cfg.polymarket.page_size == 100
    assert cfg.scoring.min_probability_to_show == 0.03
    assert cfg.scoring.max_events_per_topic == 1


def test_load_config_reads_new_keys(tmp_path):
    config_path = _write_config(
        tmp_path,
        "polymarket:\n  page_size: 50\n"
        "scoring:\n  min_probability_to_show: 0.1\n  max_events_per_topic: 3\n",
    )
    cfg = load_config(config_path)
    assert cfg.polymarket.page_size == 50
    assert cfg.scoring.min_probability_to_show == 0.1
    assert cfg.scoring.max_events_per_topic == 3


def test_load_config_rejects_unknown_discovery_key(tmp_path):
    config_path = _write_config(tmp_path, "discovery:\n  min_volume24h: 100\n")
    with pytest.raises(ValueError) as excinfo:
        load_config(config_path)
    message = str(excinfo.value)
    assert "min_volume24h" in message
    assert "discovery" in message
    assert "min_volume_24h" in message  # valid keys are listed to guide the fix


def test_load_config_rejects_unknown_polymarket_key(tmp_path):
    config_path = _write_config(tmp_path, "polymarket:\n  pagesize: 10\n")
    with pytest.raises(ValueError, match="pagesize"):
        load_config(config_path)


def test_load_config_rejects_unknown_storage_key(tmp_path):
    config_path = _write_config(tmp_path, "storage:\n  snapshot_dir: state/snapshots\n")
    with pytest.raises(ValueError, match="snapshot_dir"):
        load_config(config_path)


def test_load_config_rejects_unknown_top_level_key(tmp_path):
    config_path = _write_config(tmp_path, "run_time_local: '08:07'\n")
    with pytest.raises(ValueError, match="run_time_local"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("section", "body"),
    [
        ("ai_summary", "ai_summary:\n  enable: true\n"),
        ("notification", "notification:\n  providr: ntfy\n"),
        ("scoring", "scoring:\n  max_item: 3\n"),
    ],
)
def test_load_config_names_the_offending_section(tmp_path, section, body):
    with pytest.raises(ValueError) as excinfo:
        load_config(_write_config(tmp_path, body))
    assert f"Unknown {section} keys" in str(excinfo.value)


def test_removed_keys_are_gone_from_example_config():
    raw = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    assert "run_time_local" not in raw
    assert "snapshot_dir" not in raw["storage"]
    assert "enabled" not in raw["notification"]["telegram"]


def test_example_config_loads():
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg.polymarket.page_size == 100
    # Still wired through config even though other modules consume them.
    assert cfg.discovery.include_active_only is True
    assert cfg.discovery.include_closed is False


@pytest.mark.parametrize("body", [
    "polymarket:\n  page_size: 0\n",
    "polymarket:\n  max_retries: -1\n",
    "scoring:\n  max_items: '7'\n",
    "storage:\n  retention_days: 0\n",
    "notification:\n  provider: typo\n",
    "scoring:\n  score_weights:\n    change_signal: .nan\n",
])
def test_config_rejects_invalid_values_before_a_deployment(tmp_path, body):
    with pytest.raises(ValueError):
        load_config(_write_config(tmp_path, body))
