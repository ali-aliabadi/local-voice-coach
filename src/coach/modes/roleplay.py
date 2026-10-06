"""roleplay - the real-life moments where hesitation costs the most.

Ordering, booking, returning something, small talk with a stranger. Each session plays
one scene, and the partner is the other person in it. A scene is one row in SCENES.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .. import profile
from ._converse import converse

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "real-life scenes: ordering, booking, complaining, small talk"
ENDPOINT = "fast"
PARTNER = "other person"

# what the user is told -> who the partner plays
SCENES = {
    "You are at a restaurant ordering dinner, and you have a food allergy.": "the waiter",
    "You are calling a doctor's office to book an appointment this week.": "the receptionist",
    "You bought headphones last week and one side has stopped working.": "the shop assistant",
    "You are making small talk with a new colleague at the coffee machine.": "the new colleague",
    "You are checking into a hotel, but your room is not ready yet.": "the hotel receptionist",
    "Your upstairs neighbour plays loud music late at night.": "the neighbour",
    "You are at a party where you only know the host.": "a guest you have just met",
    "The heating in your flat has broken and you are calling the landlord.": "the landlord",
    "You are lost in a city you do not know and stop someone for directions.": "a local",
    "There is a charge on your card you do not recognise, so you call the bank.": "the bank",
    "You run into an old friend you have not seen for years.": "the old friend",
    "You want to join a gym and need to choose a membership.": "the gym staff member",
}

PROMPT = (
    "You are playing {role} in a short spoken roleplay with someone practising English. "
    "The situation, as they were told it: {scene}\n\n"
    "Stay in character and speak the way that person really would: natural everyday "
    "English, 1-3 sentences a turn. Let them lead what they need, and now and then add a "
    "small, realistic complication - something is sold out, the time they want is taken - "
    "so they have to explain, ask or negotiate. Never correct their English and never step "
    "out of the scene. If they freeze, make it easier with a simple, direct question. "
    "Everything you write is read aloud: no lists, no emoji, no stage directions."
)
OPENER = "Begin the scene in character, with the first thing your character would say."


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    # The same scene for the whole session, and again after a reload.
    scene, role = random.Random(io.session).choice(list(SCENES.items()))
    await io.send(type="scene", text=scene)
    await converse(
        endpoint,
        io,
        lambda: (
            profile.system_prompt("roleplay", PROMPT, interview=False)
            .replace("{role}", role)
            .replace("{scene}", scene)
        ),
        OPENER,
        getting_ready="Setting the scene",
    )
