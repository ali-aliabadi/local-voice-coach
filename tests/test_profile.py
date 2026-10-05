"""Who the user is, and the system prompt every mode is built from."""

import json

from coach import profile, settings, store

ENGINEER = {
    "name": "Ali",
    "role": "Backend engineer",
    "seniority": "mid-level",
    "focus": "System design.",
    "nonsense": "ignored",
}


def test_an_empty_profile_gives_the_model_no_blanks_to_guess_at():
    assert not profile.is_set()
    assert profile.as_prompt() == ""


def test_the_profile_is_given_once_and_never_recited():
    profile.save(ENGINEER)
    prompt = profile.as_prompt()
    assert profile.is_set()
    assert "Ali" in prompt and "Backend engineer" in prompt and "System design." in prompt
    assert "nonsense" not in prompt and "ignored" not in prompt  # unknown keys are dropped
    assert "Years of experience" not in prompt  # an empty field, or the model speculates
    assert "Never read this back" in prompt


def test_everyday_talk_keeps_the_name_but_not_the_engineering():
    profile.save(ENGINEER)
    assert profile.system_prompt("talk", "BASE").startswith("BASE")
    chat = profile.system_prompt("talk", "BASE", interview=False)
    assert "Ali" in chat and "Backend engineer" not in chat and "System design." not in chat


def test_the_users_own_prompt_replaces_the_modes():
    settings.set_prompt("talk", "MY OWN PROMPT")
    assert profile.system_prompt("talk", "BASE").startswith("MY OWN PROMPT")


def test_the_pacing_note_forbids_commenting_on_speech():
    note = profile.coaching_note({"answers": 9, "wpm": 105, "fillers": 4.2, "lead_in": 3.1})
    assert "105" in note and "4.2" in note
    assert "Never mention these numbers" in note and "Never correct their English" in note
    assert profile.coaching_note({}) == "" and profile.coaching_note(None) == ""
    assert "For pacing only" not in profile.system_prompt("talk", "X", pacing=False)


def test_talk_remembers_the_last_recap_when_asked_to(counted):
    session = counted()
    recap = {"recap": "They watched Se7en at home with their wife.", "answers": 2}
    store.db().execute("UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(recap), session))
    store.db().commit()
    assert "Se7en" in profile.system_prompt("talk", "X", interview=False, memory=True)
    assert "Se7en" not in profile.system_prompt("roleplay", "X", interview=False)
