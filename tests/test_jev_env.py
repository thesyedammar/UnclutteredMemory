"""Env wiring for the Jev client: key alias, model and endpoint overrides.

UNCLUTTER_JEV_API_KEY is the preferred key variable (any Jev API
key); HERMES_CUSTOM_OPENCODE_AI_API_KEY stays as the legacy
fallback. UNCLUTTER_JEV_URL overrides the endpoint so any
compatible Jev endpoint works with no code change.
"""
from uncluttered_memory import jev_client as jc


def test_key_alias_preferred_over_legacy(monkeypatch):
    monkeypatch.setenv("UNCLUTTER_JEV_API_KEY", "new-key")
    monkeypatch.setenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", "old-key")
    assert jc.JevJudgeClient().api_key == "new-key"


def test_legacy_key_still_read(monkeypatch):
    monkeypatch.delenv("UNCLUTTER_JEV_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", "old-key")
    assert jc.JevJudgeClient().api_key == "old-key"


def test_explicit_key_beats_env(monkeypatch):
    monkeypatch.setenv("UNCLUTTER_JEV_API_KEY", "env-key")
    monkeypatch.setenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", "env-old-key")
    assert jc.JevJudgeClient(api_key="arg-key").api_key == "arg-key"


def test_default_endpoint_unchanged_without_env(monkeypatch):
    monkeypatch.delenv("UNCLUTTER_JEV_URL", raising=False)
    assert jc.JevJudgeClient(api_key="k").endpoint == jc.ENDPOINT


def test_endpoint_url_env_overrides_default(monkeypatch):
    monkeypatch.setenv("UNCLUTTER_JEV_URL",
                       "https://example.test/zen/v1/systemone")
    assert (jc.JevJudgeClient(api_key="k").endpoint
            == "https://example.test/zen/v1/systemone")


def test_explicit_endpoint_beats_env(monkeypatch):
    monkeypatch.setenv("UNCLUTTER_JEV_URL", "https://example.test/x")
    j = jc.JevJudgeClient(api_key="k", endpoint="https://other.test/y")
    assert j.endpoint == "https://other.test/y"


def test_relation_pair_honors_endpoint_env(monkeypatch):
    monkeypatch.setenv("UNCLUTTER_JEV_URL", "https://example.test/sys")
    direct, slot = jc.live_relation_pair(api_key="k")
    assert direct.client.endpoint == "https://example.test/sys"
    assert slot.client.endpoint == "https://example.test/sys"


def test_model_env_still_overrides_default(monkeypatch):
    monkeypatch.setenv("UNCLUTTER_JEV_MODEL", "custom-model")
    assert jc.JevJudgeClient(api_key="k").model == "custom-model"
