"""Keeping things: settings, sessions, latency and recordings."""

from coach import history, settings, store

METRICS = {"words": 40, "wpm": 120, "fillers": 1, "pauses": 2, "longest_pause": 1, "lead_in": 1}
STORED = "SELECT COUNT(*) FROM settings WHERE key = ?"


def test_a_setting_comes_back_as_its_defaults_type():
    assert settings.get("pause_seconds") == 0.6
    settings.set("pause_seconds", "0.9")
    assert settings.get("pause_seconds") == 0.9
    assert isinstance(settings.get("history_turns"), int)


def test_a_default_is_never_stored():
    """Or saving the form would freeze it, and a better default would never land."""
    settings.set("pause_seconds", 0.6)
    assert store.db().execute(STORED, ("pause_seconds",)).fetchone()[0] == 0
    settings.set_prompt("talk", "BUILT-IN", default="BUILT-IN")
    assert store.db().execute(STORED, ("prompt:talk",)).fetchone()[0] == 0


def test_a_blank_prompt_falls_back_to_the_modes_own():
    assert settings.prompt("talk", "BUILT-IN") == "BUILT-IN"
    settings.set_prompt("talk", "be brutal")
    assert settings.prompt("talk", "BUILT-IN") == "be brutal"
    settings.set_prompt("talk", "   ")
    assert settings.prompt("talk", "BUILT-IN") == "BUILT-IN"


def test_the_form_never_sends_a_secret_to_the_browser():
    form = {f["key"]: f for f in settings.as_form({"tts_voice": ("am_puck", "af_heart")})}
    assert form["gemini_api_key"]["value"] == ""
    assert form["tts_voice"]["choices"] == ["am_puck", "af_heart"]  # filled at request time
    assert form["whisper_model"]["restart"] is True


def test_latency_is_measured_per_backend():
    one = store.start("talk", "flash-lite", "m")
    store.record(one, "interviewer", "why?", reply_ms=1000.0)
    store.record(one, "interviewer", "and then?", reply_ms=2000.0)
    two = store.start("review", "bonsai27", "m")
    store.record(two, "review", "critique", reply_ms=9000.0)
    assert store.measured_latency() == {"flash-lite": (1500.0, 2), "bonsai27": (9000.0, 1)}


def test_each_session_keeps_its_own_answers():
    """Two tabs once filed their answers under one session."""
    one, two = store.start("talk", "flash-lite", "m"), store.start("talk", "flash-lite", "m")
    store.record(one, "you", "an answer", METRICS)
    store.record(two, "you", "another", METRICS)
    assert len(store.session_scores(one)) == 1
    assert len(store.session_scores(two)) == 1


def test_a_missing_recording_is_cleared_and_zero_days_keeps_them_forever():
    session = store.start("talk", "flash-lite", "m")
    turn = store.record(session, "you", "an answer", METRICS, audio_path="/nowhere/gone.wav")
    assert store.purge_audio(0) == 0
    assert store.audio_path(turn) == "/nowhere/gone.wav"
    assert store.purge_audio(7) == 1
    assert store.audio_path(turn) is None


def test_the_trend_has_one_point_per_day_not_per_session(counted):
    counted()
    counted("review")
    trend = history.trend()
    assert len(trend) == 1
    assert trend[0]["sessions"] == 2


def test_forgetting_everything_leaves_nothing(counted):
    counted()
    store.forget_everything()
    assert history.trend() == []
    assert store.measured_latency() == {}
    assert history.count() == 0
