"""Every user-editable knob: one row each. settings.py reads and writes them.

SHARED knobs belong to the server - its models, its key, its disk - and an admin sets
them for everyone. The rest are each person's own, and start from the owner's.
"""

from dataclasses import dataclass, field
from typing import Any

WHISPER_CHOICES = ("tiny.en", "base.en", "small.en", "medium.en", "distil-small.en")


@dataclass(frozen=True)
class Setting:
    default: Any
    label: str
    group: str
    kind: str = "text"  # text | number | password | select | textarea
    help: str = ""
    secret: bool = False  # never sent back to the browser
    restart: bool = False  # takes effect on the next server start
    step: float | None = None
    choices: tuple[str, ...] = field(default_factory=tuple)


SPEC: dict[str, Setting] = {
    # ---- Backends ----
    "gemini_api_key": Setting(
        "",
        "Gemini API keys",
        "Backends",
        kind="password",
        secret=True,
        help="Free at aistudio.google.com/apikey. Several, comma-separated, are a pool. Stored locally.",
    ),
    "lm_studio_url": Setting(
        "http://localhost:1234/v1",
        "LM Studio URL",
        "Backends",
        help="Where to reach local models. Leave as-is unless you changed the port.",
    ),
    # ---- Scoring ----
    "pause_seconds": Setting(
        0.6,
        "Pause threshold",
        "Scoring",
        kind="number",
        step=0.1,
        help="A silence longer than this counts as a hesitation. Lower it to be harder on yourself.",
    ),
    "filler_words": Setting(
        "um uh er ah hmm mm",
        "Filler words",
        "Scoring",
        help="Space separated. Repeated letters are matched too, so 'mm' also catches 'mmmm'.",
    ),
    "audio_retention_days": Setting(
        0,  # they never leave this machine, so nothing is gained by deleting them
        "Keep recordings for (days)",
        "Scoring",
        kind="number",
        help="0 keeps them forever. They never leave this machine; they take about 40MB "
        "per hour of practice. Set a number of days to have older ones deleted.",
    ),
    # ---- Model ----
    "temperature": Setting(0.7, "Temperature", "Model", kind="number", step=0.1),
    "history_turns": Setting(
        50,
        "History turns",
        "Model",
        kind="number",
        help="Answer/reply pairs the model can see. 50 covers a whole session; at 8 it "
        "forgot what you said ten minutes ago. Lower it only to save tokens.",
    ),
    "reply_max_tokens": Setting(200, "Reply max tokens", "Model", kind="number"),
    "review_max_tokens": Setting(
        2500,
        "Review max tokens",
        "Model",
        kind="number",
        help="Thinking models spend this budget reasoning before they write. Keep it generous.",
    ),
    "tts_voice": Setting("am_puck", "Voice", "Model", kind="select"),
    "tts_speed": Setting(1.0, "Speech speed", "Model", kind="number", step=0.1),
    "vary_voice": Setting(
        "on",
        "A different accent each session",
        "Model",
        kind="select",
        choices=("on", "off"),
        help="American and British, men and women, so your ear is not tuned to one voice. "
        "Off uses the Voice above every time.",
    ),
    # ---- Practice ----
    "talking": Setting(
        "space",
        "Talking",
        "Practice",
        kind="select",
        choices=("space", "hybrid"),
        help="Space: tap or press space to start and to stop. Hybrid: the mic stays open, "
        "your voice starts the answer and a pause ends it, and talking over the partner cuts "
        "in, as in a real conversation - space still works. 'Before you spoke' then counts "
        "from the end of their sentence. Hybrid hears best with headphones.",
    ),
    "hands_free_silence": Setting(
        3.0,
        "Hybrid: quiet before it stops",
        "Practice",
        kind="number",
        step=0.5,
        help="Seconds of silence that end your answer. Keep it well above the pause "
        "threshold, so thinking mid-sentence is not cut off.",
    ),
    "answer_limit": Setting(
        300,
        "Interview: longest answer",
        "Practice",
        kind="number",
        step=15,
        help="The interviewer gives each question its own time - about a minute for "
        "yourself, more for a design - and stops you past it, as real ones do. This is "
        "the most any answer gets. 0 never stops you.",
    ),
    # ---- Coach ----
    "coach_backend": Setting(
        "flash-lite",
        "Coach model",
        "Coach",
        kind="select",
        help="Writes notes on each answer in the background, read after the session: "
        "grammar, word choice, phrases to use. 'off' turns it off. Flash-Lite wrote notes "
        "as useful as Flash in 2s instead of 20s, and its free tier covers an hour a day; "
        "Flash's free tier allows 5 requests a minute. bonsai27 keeps it offline.",
    ),
    # ---- Telegram, through Relay (see relay.py; switched on by RELAY_* in .env) ----
    "relay_session_report": Setting(
        "on",
        "Report after each session",
        "Telegram",
        kind="select",
        choices=("on", "off"),
        help="Telegram needs RELAY_URL, RELAY_API_KEY, RELAY_APP and RELAY_USER in .env.",
    ),
    "relay_weekly": Setting(
        "on",
        "Last week's report",
        "Telegram",
        kind="select",
        choices=("on", "off"),
        help="Each day of last week, against the week before. Sent after the first session "
        "of a new week: the app only runs while you practise.",
    ),
    "relay_lessons": Setting(
        "on",
        "Include the coach's lessons",
        "Telegram",
        kind="select",
        choices=("on", "off"),
        help="The lessons quote your own sentences, so that text ends up in your Telegram "
        "chat. Audio never does.",
    ),
    "sheet_backend": Setting(
        "flash",
        "Study sheet model",
        "Coach",
        kind="select",
        help="Writes a page or two after each session of 3+ answers: fixes worth the most, "
        "phrases for your conversations, what to practise tomorrow. A PDF on the session "
        "page, and images on Telegram. One request per session, so a stronger model is "
        "affordable here. 'off' turns it off.",
    ),
    "verdict_backend": Setting(
        "flash",
        "Interview verdict model",
        "Coach",
        kind="select",
        help="After each interview, the feedback a real interviewer would submit: a rating "
        "out of 10, hire or not, a score for each area. Telegram gets only the headline.",
    ),
    "relay_sheet": Setting(
        "on", "Send the study sheet", "Telegram", kind="select", choices=("on", "off")
    ),
    "whisper_model": Setting(
        "small.en",
        "Whisper model",
        "Model",
        kind="select",
        restart=True,
        choices=WHISPER_CHOICES,
        help="Smaller is faster and less accurate.",
    ),
}

SHARED = {k for k, s in SPEC.items() if s.group == "Backends" or s.restart} | {
    "audio_retention_days"
}
