"""The voice: phrase pools, variation without wallpaper, kind lines.

Pure. All user-visible copy lives here (AGENTS.md).
"""
from __future__ import annotations

import random

# ---- pools (>=6 each; the daemon logs which was used so we can tune) ----

FIRE = [
    "The kettle's on, hunny — {text} wants your attention.",
    "Threshold time: {text}. Just noting it exists.",
    "Gentle bell — {text}. No rush, just real.",
    "{text}. It's on the table, love.",
    "Psst. {text}. That's all, just saying.",
    "Little chime: {text}. Here when you're ready.",
]

FIRE2 = [
    "Still here about {text}, hunny — letting you know again, no guilt.",
    "{text}, once more. The clock and I both notice, neither of us judges.",
    "Second bell for {text}. It waits well, but it wants you to know.",
    "Hey — {text} again. Quietly insistent, like a cat at a door.",
]

FIRE3 = [
    "This one's staying lit: {text}. I'll sit with you in the corner till it's handled.",
    "{text} — I've stopped whispering. Come say done, or say didn't. Both are honest.",
    "Persistent little flame about {text}. Pick a door: done, didn't, or later.",
]

DONE_LINES = [
    "There it is. Logged with a little candle.",
    "Done and witnessed. Well met.",
    "One candle lit for {text}. Lovely.",
]

DIDNT_LINES = [
    "It'll wait. It's not going anywhere.",
    "Honest answer, honestly logged. That's the deal we have.",
    "Noted, no penalty. Tomorrow-you can look at it fresh.",
]

SNOOZE_LINES = [
    "Later, then. I'll nudge again at the right time.",
    "Rests a while. I've got the timer.",
]

PAIR_LINES = [
    "She's asked me to let you know: {text} has been trying to get through for a while now. A gentle word from you might help.",
]

TELLING_OPENERS = [
    "The hearth report for today:",
    "Here's what today held:",
    "The day, told back:",
]

TELLING_EMPTY = [
    "Nothing was logged done today — and that's allowed. The day still happened.",
    "A quiet ledger today. No candles, no judgment.",
]

LIST_EMPTY = [
    "No reminders yet — the slate is clean. `nudge add` when something wants remembering.",
    "Nothing being watched over just now. Add one whenever you like.",
    "An empty shelf, not a failure. `nudge add` puts something on it.",
]

# ---- selection ----

def pick(pool: list[str], last_used: str | None = None,
         rng: random.Random | None = None) -> str:
    """Pick a phrase, never the one just used (wallpaper-effect rule)."""
    rng = rng or random.Random()
    if len(pool) > 1 and last_used in pool:
        pool = [p for p in pool if p != last_used]
    return rng.choice(pool)


def render(pool: list[str], text: str, note: str = "",
           last_used: str | None = None, rng: random.Random | None = None) -> str:
    """Fill the chosen phrase; weave the note in when there is one."""
    phrase = pick(pool, last_used, rng)
    body = phrase.format(text=text)
    if note:
        body = f"{body} ({note})"
    return body
