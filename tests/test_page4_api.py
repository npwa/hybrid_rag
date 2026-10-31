"""Page 4 API on the demo dataset: T-P4-2 (reconciliation), flags, windows, empty case, triage hooks."""
from fastapi.testclient import TestClient

from console.api import create_app


def summary(client, days=30):
    r = client.get(f"/api/v1/toolcalls/summary?days={days}")
    assert r.status_code == 200, r.text
    return r.json()


def test_counts_reconcile_between_agent_and_desktop(client):                         # T-P4-2
    d = summary(client)
    t = d["totals"]
    assert d["available"] and t["tool_starts"] == t["matched"] + t["agent_starts_without_desktop_call"]
    assert d["desktop"]["calls"] == t["matched"] + t["desktop_calls_without_agent_start"]
    assert t["agent_starts_without_desktop_call"] == 1 and t["desktop_calls_without_agent_start"] == 0   # the outage morning
    assert sum(r["tool_starts"] for r in d["by_day"]) == t["tool_starts"]
    assert sum(r["matched"] for r in d["by_day"]) == t["matched"]
    assert sum(r["turns"] for r in d["by_day"]) == t["turns"] == sum(m["turns"] for m in d["models"])
    assert sum(d["desktop"]["by_outcome"].values()) == d["desktop"]["calls"]


def test_models_story_small_model_writes_calls_as_text(client):
    d = summary(client)
    models = {m["model"]: m for m in d["models"]}
    small, big = models["ollama/qwen2.5:14b-instruct"], models["ollama/qwen3.6:35b-a3b"]
    assert small["looks_like"] > 0 and small["tool_rate"] < 0.9
    assert big["looks_like"] == 0 and big["tool_rate"] == 1.0
    assert d["totals"]["looks_like_tool_call"] == small["looks_like"]
    first, last = d["by_day"][0], d["by_day"][-1]
    assert first["models"] == ["ollama/qwen2.5:14b-instruct"] and last["models"] == ["ollama/qwen3.6:35b-a3b"]


def test_flags_cover_outage_gap_preflight_and_text_calls(client):                    # FR-4.4
    d = summary(client)
    kinds = {f["kind"] for f in d["flags"]}
    assert {"mcp_connect_failure", "tool_start_without_desktop_call", "host_gap", "provider_preflight_failed", "looks_like_tool_call"} <= kinds
    assert [f["ts"] for f in d["flags"]] == sorted((f["ts"] for f in d["flags"]), reverse=True)
    outage = next(r for r in d["by_day"] if r["mcp_connect_failures"])
    assert outage["agent_starts_without_desktop_call"] == 1 and outage["host_gaps"] == 1


def test_time_to_tool_stats_and_samples(client):
    d = summary(client)
    s = d["time_to_tool_ms"]
    assert s["count"] == d["totals"]["tool_starts"] and s["p50"] <= s["p95"] <= s["max"] == 50248
    assert len(d["time_to_tool_samples"]) == s["count"] and all("model" in x for x in d["time_to_tool_samples"])


def test_period_window_limits_the_data(client):
    week = summary(client, days=7)
    month = summary(client, days=30)
    assert week["totals"]["turns"] < month["totals"]["turns"]
    assert all(r["day"] >= "2026-10-24" for r in week["by_day"])
    assert client.get("/api/v1/toolcalls/summary?days=0").status_code == 422
    assert client.get("/api/v1/toolcalls/summary?days=9999").status_code == 422


def test_sources_describe_the_copied_logs(client):
    d = summary(client)
    src = d["sources"]
    assert src["files"] == 14 and src["newest_file"] == "openclaw-2026-10-30.log" and src["pull_script"].endswith("pull_agent_logs.sh")
    assert src["config_summary"]["primary_model"] == "ollama/qwen3.6:35b-a3b" and src["age_hours"] is not None and src["age_hours"] < 36
    assert d["jsonl_days_with_mcp_records"] == 14


def test_no_agent_logs_gives_a_helpful_empty_response(demo_config, tmp_path):
    demo_config.agent_logs_dir = tmp_path / "nothing"
    d = summary(TestClient(create_app(demo_config)))
    assert d["available"] is False and "pull_agent_logs.sh" in d["detail"] and d["sources"]["files"] == 0


def test_without_desktop_jsonl_agent_starts_show_as_unseen(demo_config, tmp_path):
    demo_config.logs_dir = tmp_path / "emptylogs"               # no query logs at all (e.g. before milestone M1)
    demo_config.logs_dir.mkdir()
    d = summary(TestClient(create_app(demo_config)))
    assert d["desktop"]["calls"] == 0 and d["totals"]["matched"] == 0
    assert d["totals"]["agent_starts_without_desktop_call"] == d["totals"]["tool_starts"] and d["jsonl_days_with_mcp_records"] == 0


def test_demo_clock_is_frozen(demo_config):
    assert demo_config.now() == demo_config.now() and demo_config.now().year == 2026
