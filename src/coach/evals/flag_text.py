"""Reading a finding's prose against a computed flag. Deliberately narrow.

The code checks used to confirm only that a flagged exercise appeared in concerns, so a
concern saying the opposite of its flag passed every check (docs/findings.md entry 13).
This module reads one finding's text for two things, by word families and nothing
cleverer:

- whether it states the flagged condition, without negating it: a stall (the top set
  unchanged), a fall in estimated strength, or sessions missed against the baseline;
- whether it says the opposite: progress for a stall, a rise for a fall, full attendance
  for missed sessions, or the condition itself negated ("not stalled").

Text is split into clauses. A cue is negated by one of the three words before it ("not
progressing", "hasn't increased", "halting the advances") or by a stopping word just
after it ("progress has stalled"). Some cues are not claims about this week and are
ignored: after "to", "should" or a similar word (a wish), and next to "after", "earlier",
"until" or a similar word (earlier weeks). For an exercise's flag, a clause naming another
exercise or "other lifts" is not read, and nor is a cue about effort or volume: "the
rising RPE" beside an unchanged top set is the rising-effort story, not progress. The
flagged exercise's own name is read as "it", so its words neither name another exercise
("incline" in Seated Incline Curl) nor make a claim ("decline" in Decline Bench Press).

What it does not do, by design: check the numbers a finding quotes (the kilogram and
percentage checks do, within their own limits), read the headline or suggestions, or
understand phrasing outside the word families below. docs/checks.md lists these limits;
beyond them, the model-graded rubric is the only judge of meaning.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

_NUMBER = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a single)"


def _family(*patterns: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b")


#: Progress or a rise: the opposite of a stall or a fall, unless negated.
PROGRESS = _family(
    r"progress(?:es|ed|ing)?",
    r"improv(?:e|es|ed|ing|ement|ements)",
    r"increas(?:e|es|ed|ing)",
    r"ris(?:e|es|en|ing)|rose",
    r"climb(?:s|ed|ing)?",
    r"gain(?:s|ed|ing)?",
    r"advanc(?:e|es|ed|ing)",
    r"mov(?:ed|ing)(?: up)?|budg(?:e|ed|ing)",
    r"(?:went|gone|going|is|are|was|were) up",
    r"up (?:by )?\d[\d.]*|up from",
    r"new (?:best|high|pr|personal best|personal record)|(?:rep )?pr",
)
#: A fall. States a fall in strength unless negated; negated, it is the opposite.
FALL = _family(
    r"down(?:ward)?",
    r"dropp(?:ed|ing)|drops?",
    r"fell|fall(?:s|en|ing)?",
    r"declin(?:e|es|ed|ing)",
    r"decreas(?:e|es|ed|ing)",
    r"regress(?:es|ed|ing|ion)?",
    r"slipp(?:ed|ing)|slips?",
    r"lost|los(?:e|es|ing)",
    r"lower(?:ed)?(?! back)",
    r"reduc(?:ed|tion)",
    r"weaker|worse",
    r"backwards?",
    r"slid(?:e|es|ing)?",
)
#: The top set unchanged. States a stall unless negated; negated ("not stalled"), the opposite.
STALL = _family(
    r"stall(?:s|ed|ing)?",
    r"plateau(?:s|ed|ing)?",
    r"unchanged",
    r"flat(?:lined|lining)?",
    r"stuck",
    r"stagna(?:nt|ted|ting|tion)",
    r"static",
    r"held|holding|remain(?:s|ed)?|stay(?:s|ed|ing)?|sat|sitting|locked",
    r"same (?:[\d.]+ ?kg (?:x \d+ )?)?(?:top set|load|weight|numbers)",
    r"repeat(?:s|ed|ing)?",
    r"still (?:at )?\d[\d.]*",
    r"same (?:as|for)",
)
#: Change. Read only when negated ("hasn't changed", "no change"); then it states a stall.
CHANGE = _family(r"chang(?:e|es|ed|ing)")
#: A stated duration. States a stall only when the finding states no rise and no fall, since
#: "rose for five weeks" is not a stall.
DURATION = _family(
    rf"for (?:the )?(?:last |past )?{_NUMBER} (?:consecutive |straight |successive )?weeks",
    rf"{_NUMBER} (?:consecutive|straight|successive) weeks",
    r"weeks? (?:running|in a row)",
    r"every week|each week|week after week|week on week",
    r"since (?:week |w)?\d+",
)
#: Sessions short of the baseline.
SHORTFALL = _family(
    r"miss(?:ed|es|ing)",
    r"skipp(?:ed|ing)",
    r"fewer",
    rf"only {_NUMBER} (?:sessions?|workouts?|days?)",
    r"(?:trained|lifted) (?:only )?(?:once|twice)|(?:once|twice) this week",
    r"below (?:the |your |usual )?(?:baseline|average|usual)",
    r"short of",
    r"(?:lower|reduced|less|dropped) (?:training )?(?:frequency|attendance)",
    rf"{_NUMBER} sessions?",
    rf"{_NUMBER} (?:of|out of) {_NUMBER}",
)
#: Full attendance: the opposite of missed sessions.
ATTENDANCE = _family(
    rf"(?:all|every) (?:{_NUMBER} )?(?:planned |scheduled )?(?:sessions?|workouts?)",
    r"full attendance",
    r"match(?:ed|es|ing)? (?:the |your )?(?:baseline|usual|plan)",
    r"on (?:track|target|plan|baseline)",
    r"consistent (?:attendance|frequency|schedule|training)",
)
#: A cue whose subject is one of these is not about the top set or strength.
_EFFORT = _family(
    r"rpe",
    r"effort",
    r"exertion",
    r"fatigue",
    r"difficulty",
    r"intensity",
    r"volume",
    r"tonnage",
    r"sleep",
    r"recovery",
)
#: A clause about something other than the flagged exercise.
_OTHERS = _family(
    r"other (?:lifts?|exercises?|movements?)",
    r"the rest",
    r"elsewhere",
    r"everything else",
    r"remaining (?:lifts?|exercises?)",
    r"all (?:lifts?|exercises?)",
)
_NEGATORS = frozenset(
    {
        "not",
        "no",
        "never",
        "without",
        "nor",
        "neither",
        "none",
        "nothing",
        "zero",
        "cannot",
        "lack",
        "lacks",
        "lacking",
        "hardly",
        "barely",
    }
)
#: Words that stop what follows them, however long the noun phrase: "halting the steady
#: weekly advances". They negate every cue after them in the clause.
_HALTERS = frozenset(
    {
        "halting",
        "halted",
        "ending",
        "ended",
        "interrupting",
        "interrupted",
        "breaking",
        "stopping",
        "stopped",
        "ceasing",
    }
)
#: A cue next to one of these is about earlier weeks ("after steady progress earlier"), not a
#: claim about now. "since" counts only before a cue: "flat since week 36" is current.
_PAST_BEFORE = frozenset(
    {"after", "following", "since", "previous", "previously", "earlier", "prior", "last"}
)
_PAST_AFTER = frozenset({"earlier", "previously", "before", "until", "till", "prior"})
_STOPPERS = frozenset(
    {
        "stalled",
        "stalling",
        "stopped",
        "stopping",
        "halted",
        "paused",
        "ceased",
        "plateaued",
        "flatlined",
        "slowed",
        "reversed",
    }
)
_IRREALIS = frozenset(
    {
        "to",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "must",
        "need",
        "needs",
        "try",
        "trying",
        "aim",
        "hope",
        "expect",
        "want",
        "help",
        "helps",
        "let",
        "next",
    }
)
_SPLIT = re.compile(
    r"\.(?!\d)|[;:!?()\[\],]|\s[-\u2013\u2014]+\s"
    r"|\b(?:while|whereas|but|although|though|however|unlike|despite|compared|and|with)\b"
    r"|(?<!same )\bas\b"
)
_RELATIVE = re.compile(r"^\s*(?:which|who|that|where)\b")
_WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class Reading:
    """What one finding's text says about one flag."""

    #: The text states the flagged condition and nothing opposite to it.
    states: bool
    #: The first clause that says the opposite of the flag, or None.
    opposite: str | None
    #: Other flag kinds the text states instead, for a "wrong reason" detail.
    instead: tuple[str, ...]


def _normalise(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"\bno longer\b", "not", t)
    t = re.sub(r"\b(?:failed|fails|failing|yet|unable) to\b", "not", t)
    t = re.sub(r"\b(?:stopped|ceased|halted)\b(?=\s+\w+ing\b)", "not", t)
    return re.sub(r"\black of\b", "no", t)


def _clauses(text: str) -> list[str]:
    """Split into clauses; a relative clause ("which kept climbing") stays with its noun."""
    clauses: list[str] = []
    for part in _SPLIT.split(text):
        if clauses and _RELATIVE.match(part):
            clauses[-1] = f"{clauses[-1]} {part}"
        elif part.strip():
            clauses.append(part)
    return clauses


def _base(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", title).strip().lower()


def other_names(flagged: str, names: Iterable[str]) -> list[str]:
    """How the other exercises may be named in prose.

    The title without its equipment, and its first word when no other exercise shares it:
    "squat", but not "seated" when there are two seated exercises.
    """
    bases = {name: _base(name) for name in names if name != "Overall"}
    firsts = Counter(base.split()[0] for base in bases.values() if base)
    own = _base(flagged).split()[0] if _base(flagged) else ""
    aliases: list[str] = []
    for name, base in bases.items():
        if name == flagged or not base:
            continue
        aliases.append(base)
        first = base.split()[0]
        if firsts[first] == 1 and first != own and len(first) > 3:
            aliases.append(first)
    return aliases


def _own_name_as_it(clause: str, own: str, others: Sequence[str]) -> str:
    """The clause with the flagged exercise's name, without its equipment, replaced by "it".

    A longer name that contains it (Straight Arm Lat Pulldown, for Lat Pulldown) belongs to
    another exercise and is left as written.
    """
    name = _base(own)
    if not name or name == "overall":
        return clause
    longer = sorted(
        (a for a in others if a != name and re.search(rf"\b{re.escape(name)}\b", a)),
        key=len,
        reverse=True,
    )
    pattern = re.compile("|".join(rf"\b{re.escape(n)}\b" for n in [*longer, name]))
    return pattern.sub(lambda m: "it" if m.group(0) == name else m.group(0), clause)


def _about_something_else(clause: str, others: Sequence[str]) -> bool:
    return bool(_OTHERS.search(clause)) or any(
        re.search(rf"\b{re.escape(alias)}\b", clause) for alias in others
    )


def _cues(
    clauses: Sequence[str], family: re.Pattern[str], *, effort_counts: bool
) -> Iterator[tuple[str, bool]]:
    """Each claim the family makes in the clauses, as (clause, negated). Wishes are skipped."""
    for clause in clauses:
        for match in family.finditer(clause):
            before = _WORD.findall(clause[: match.start()])
            after = _WORD.findall(clause[match.end() :])[:3]
            if any(word in _IRREALIS for word in before[-2:]):
                continue
            if any(w in _PAST_BEFORE for w in before[-3:]) or any(w in _PAST_AFTER for w in after):
                continue
            if not effort_counts and any(
                _EFFORT.fullmatch(word) for word in [*before[-3:], *after[:2]]
            ):
                continue
            negated = (
                any(w in _NEGATORS or w.endswith("n't") for w in before[-3:])
                or any(w in _HALTERS for w in before)
                or any(w in _STOPPERS for w in after)
            )
            yield clause.strip(), negated


def _first(
    clauses: Sequence[str], family: re.Pattern[str], negated: bool, *, effort_counts: bool = False
) -> str | None:
    for clause, is_negated in _cues(clauses, family, effort_counts=effort_counts):
        if is_negated == negated:
            return clause
    return None


def read(kind: str, text: str, others: Sequence[str] = (), own: str = "") -> Reading:
    """Read ``text`` against a flag of ``kind``.

    ``others`` names the other exercises, as ``other_names`` gives them; ``own`` is the
    flagged exercise, whose name is read as "it" rather than as words.
    """
    clauses = _clauses(_normalise(text))
    if kind == "sessions_missed":
        opposite = _first(clauses, ATTENDANCE, False, effort_counts=True) or _first(
            clauses, SHORTFALL, True, effort_counts=True
        )
        states = _first(clauses, SHORTFALL, False, effort_counts=True) is not None
        return Reading(states=states and opposite is None, opposite=opposite, instead=())

    named = (_own_name_as_it(c, own, others) for c in clauses)
    readable = [c for c in named if not _about_something_else(c, others)]
    rise = _first(readable, PROGRESS, False)
    fall = _first(readable, FALL, False)
    if kind == "stall":
        opposite = rise or _first(readable, STALL, True)
        states = bool(
            _first(readable, STALL, False)
            or _first(readable, PROGRESS, True)
            or _first(readable, CHANGE, True)
            or (not rise and not fall and _first(readable, DURATION, False))
        )
        instead = ("a fall",) if not states and fall else ()
    elif kind == "e1rm_drop_4w":
        opposite = rise or _first(readable, FALL, True)
        states = fall is not None
        said_stall = _first(readable, STALL, False) or _first(readable, CHANGE, True)
        instead = ("a stall",) if not states and said_stall else ()
    else:
        raise ValueError(f"unknown flag kind {kind!r}")
    return Reading(states=states and opposite is None, opposite=opposite, instead=instead)
