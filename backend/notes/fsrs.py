"""FSRS-5 spaced-repetition scheduler (Free Spaced Repetition Scheduler).

Formulas follow the published FSRS-5 algorithm with its default parameters:
https://github.com/open-spaced-repetition/fsrs4anki/wiki/The-Algorithm
"""
import datetime as dt
import math
import random
from dataclasses import dataclass, replace

W = (
    0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192,
    1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621,
)
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # 19/81
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4

LEARNING_STEPS = [dt.timedelta(minutes=1), dt.timedelta(minutes=10)]
RELEARNING_STEPS = [dt.timedelta(minutes=10)]
MAX_INTERVAL = 36500


@dataclass
class State:
    state: str = "new"  # new | learning | review | relearning
    stability: float = 0.0
    difficulty: float = 0.0
    due: dt.datetime | None = None
    last_review: dt.datetime | None = None
    reps: int = 0
    lapses: int = 0
    step: int = 0


def _clamp_d(d: float) -> float:
    return min(10.0, max(1.0, d))


def init_stability(g: int) -> float:
    return max(W[g - 1], 0.1)


def init_difficulty(g: int) -> float:
    return _clamp_d(W[4] - math.exp(W[5] * (g - 1)) + 1)


def next_difficulty(d: float, g: int) -> float:
    delta = -W[6] * (g - 3)
    damped = d + delta * (10 - d) / 9
    return _clamp_d(W[7] * init_difficulty(EASY) + (1 - W[7]) * damped)


def retrievability(elapsed_days: float, s: float) -> float:
    if s <= 0:
        return 0.0
    return (1 + FACTOR * elapsed_days / s) ** DECAY


def recall_stability(d: float, s: float, r: float, g: int) -> float:
    hard = W[15] if g == HARD else 1.0
    easy = W[16] if g == EASY else 1.0
    return s * (
        1 + math.exp(W[8]) * (11 - d) * s ** -W[9] * (math.exp(W[10] * (1 - r)) - 1) * hard * easy
    )


def forget_stability(d: float, s: float, r: float) -> float:
    new = W[11] * d ** -W[12] * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
    return min(new, s / math.exp(W[17] * W[18]))


def short_term_stability(s: float, g: int) -> float:
    return s * math.exp(W[17] * (g - 3 + W[18]))


def interval_days(s: float, retention: float) -> int:
    ivl = s / FACTOR * (retention ** (1 / DECAY) - 1)
    return int(min(MAX_INTERVAL, max(1, round(ivl))))


def _fuzz(ivl: int, seed: str) -> int:
    if ivl < 3:
        return ivl
    rng = random.Random(seed)
    spread = max(1, round(ivl * 0.05))
    return max(2, ivl + rng.randint(-spread, spread))


def review(card: State, g: int, now: dt.datetime, retention: float = 0.9, seed: str = "") -> tuple[State, float]:
    """Apply a rating. Returns the new state and the scheduled interval in days."""
    c = replace(card)
    elapsed = (now - c.last_review).total_seconds() / 86400 if c.last_review else 0.0

    def to_review(s_good: float, s_this: float):
        ivl = interval_days(s_this, retention)
        if g == EASY:
            ivl = max(ivl, interval_days(s_good, retention) + 1)
        ivl = _fuzz(ivl, seed + str(c.reps))
        c.state, c.step = "review", 0
        c.due = now + dt.timedelta(days=ivl)
        return float(ivl)

    if c.state == "new":
        c.difficulty = init_difficulty(g)
        c.stability = init_stability(g)
        if g == EASY:
            scheduled = to_review(init_stability(GOOD), c.stability)
        else:
            c.state = "learning"
            c.step = 0 if g == AGAIN else min(1, len(LEARNING_STEPS) - 1) if g == GOOD else 0
            step = LEARNING_STEPS[c.step]
            if g == HARD:
                step = (LEARNING_STEPS[0] + LEARNING_STEPS[-1]) / 2 if len(LEARNING_STEPS) > 1 else LEARNING_STEPS[0] * 1.5
            c.due = now + step
            scheduled = step.total_seconds() / 86400
    elif c.state in ("learning", "relearning"):
        steps = LEARNING_STEPS if c.state == "learning" else RELEARNING_STEPS
        c.stability = short_term_stability(c.stability, g)
        c.difficulty = next_difficulty(c.difficulty, g)
        if g == AGAIN:
            c.step = 0
            c.due = now + steps[0]
            scheduled = steps[0].total_seconds() / 86400
        elif g == HARD:
            delay = steps[c.step] * 1.5 if c.step == 0 and len(steps) == 1 else steps[c.step]
            c.due = now + delay
            scheduled = delay.total_seconds() / 86400
        elif g == GOOD and c.step + 1 < len(steps):
            c.step += 1
            c.due = now + steps[c.step]
            scheduled = steps[c.step].total_seconds() / 86400
        else:
            scheduled = to_review(short_term_stability(card.stability, GOOD), c.stability)
    else:  # review
        r = retrievability(elapsed, c.stability)
        old_d, old_s = c.difficulty, c.stability
        c.difficulty = next_difficulty(old_d, g)
        if g == AGAIN:
            c.lapses += 1
            c.stability = forget_stability(old_d, old_s, r)
            c.state, c.step = "relearning", 0
            c.due = now + RELEARNING_STEPS[0]
            scheduled = RELEARNING_STEPS[0].total_seconds() / 86400
        else:
            s_hard = recall_stability(old_d, old_s, r, HARD)
            s_good = recall_stability(old_d, old_s, r, GOOD)
            s_easy = recall_stability(old_d, old_s, r, EASY)
            i_hard = interval_days(s_hard, retention)
            i_good = max(interval_days(s_good, retention), i_hard + 1)
            i_easy = max(interval_days(s_easy, retention), i_good + 1)
            c.stability = {HARD: s_hard, GOOD: s_good, EASY: s_easy}[g]
            ivl = _fuzz({HARD: i_hard, GOOD: i_good, EASY: i_easy}[g], seed + str(c.reps))
            c.state, c.step = "review", 0
            c.due = now + dt.timedelta(days=ivl)
            scheduled = float(ivl)
    c.reps += 1
    c.last_review = now
    return c, scheduled


def preview(card: State, now: dt.datetime, retention: float = 0.9, seed: str = "") -> dict[int, float]:
    """Interval in days each rating would give, for labelling the answer buttons."""
    return {g: review(card, g, now, retention, seed)[1] for g in (AGAIN, HARD, GOOD, EASY)}
