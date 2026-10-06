"""Where to cut a reply that is still streaming in, so it can be spoken as it arrives.

Kokoro voices a chunk at a time, and the user hears nothing until the first chunk is
voiced - so where the cuts fall decides both how natural the speech sounds and how long
the user waits. Pure text in, text out: no model, no audio.
"""

import re
from collections.abc import Container, Iterator

from . import config

# A sentence ends at .!?… when the next thing is whitespace or the end of the buffer.
# "3.5" never matches, because the dot there is followed by a digit.
TERMINATOR = re.compile(r"[.!?…]+[\"')\]]*(?=\s|$)")
ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e|No|Inc|Ltd|Jr|Sr)\.$")


def _boundaries(text: str) -> Iterator[int]:
    """Offsets where a sentence genuinely ends. Abbreviations are not endings."""
    settled = len(text.rstrip())
    for match in TERMINATOR.finditer(text):
        head = text[: match.end()]
        if ABBREVIATION.search(head):
            continue
        # A trailing "3." may still become "3.5" once the next token lands.
        if match.end() >= settled and len(head) >= 2 and head[-1] == "." and head[-2].isdigit():
            continue
        yield match.end()


# A clause ends at , ; : or a dash followed by a space - so "1,000" never splits.
CLAUSE = re.compile(r"[,;:\u2013\u2014](?=\s)")
EAGER_WORDS = 3  # a first chunk shorter than this sounds clipped


def split_for_speech(buffer: str, flush: bool = False, eager: bool = False) -> tuple[str, str]:
    """Split the buffer into (speak now, keep buffering).

    Splits at the LAST complete sentence inside the buffer, rather than only when the
    buffer happens to end on one. Models stream several words per token, so a boundary
    usually lands in the middle of a token ("own. Walk me"). A check that only looked at
    the tail missed it, the buffer kept growing, and the length cap eventually cut a
    sentence in half - which is why the interviewer stopped mid-sentence.

    The returned buffer is never stripped: the trailing space is what keeps the next
    token from being glued onto the last word.

    `eager` is for the first words of a reply, which are the wait the user feels: a
    27-word opening sentence took Kokoro 1.5s to voice before anything played, so the
    first chunk may end at a clause instead ("Oh, nice one,") once it has a few words.
    """
    if flush:
        return buffer.strip(), ""
    if not buffer.strip():
        return "", buffer

    cuts = list(_boundaries(buffer))
    if cuts:
        return buffer[: cuts[-1]].strip(), buffer[cuts[-1] :].lstrip()
    if eager:
        for clause in CLAUSE.finditer(buffer):
            if len(buffer[: clause.end()].split()) >= EAGER_WORDS:
                return buffer[: clause.end()].strip(), buffer[clause.end() :].lstrip()

    # Nothing has ended yet. Only give up waiting once this has run on far too long, and
    # then break between words - never inside one.
    if len(buffer.strip()) >= config.MAX_CHARS_BEFORE_FLUSH:
        space = buffer.rstrip().rfind(" ")
        if space > 0:
            return buffer[:space].strip(), buffer[space:].lstrip()
    return "", buffer


SPEAKER = re.compile(r"^\s*([A-Z][A-Z]+)\s*:\s*")


def split_speaker(text: str, cast: Container[str]) -> tuple[str | None, str]:
    """Pull a leading 'NAME:' off a reply. Returns (name if it is in `cast`, rest)."""
    match = SPEAKER.match(text)
    if not match:
        return None, text
    name = match.group(1)
    return (name if name in cast else None), text[match.end() :].strip()
