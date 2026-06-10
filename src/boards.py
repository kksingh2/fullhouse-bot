"""Board texture classifier."""
from dataclasses import dataclass
from typing import List

RANK_VAL = {r: i for i, r in enumerate("23456789TJQKA", start=2)}


@dataclass
class BoardTexture:
    paired: bool = False
    trips: bool = False
    monotone: bool = False
    two_tone: bool = False
    flush_completed: bool = False
    straight_possible: bool = False
    high_card: int = 0
    connectedness: float = 0.0
    wet_score: float = 0.0


def classify(community: List[str]) -> BoardTexture:
    t = BoardTexture()
    if not community:
        return t
    ranks = [c[0] for c in community]
    suits = [c[1] for c in community]
    vals = sorted([RANK_VAL[r] for r in ranks])

    # pairing
    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    max_count = max(rank_counts.values())
    t.paired = max_count >= 2
    t.trips = max_count >= 3

    # suits
    suit_counts = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1
    max_suit = max(suit_counts.values()) if suit_counts else 0
    t.monotone = max_suit >= 3 and len(community) == 3
    t.two_tone = max_suit == 2 and len(community) == 3
    t.flush_completed = max_suit >= 3 and len(community) >= 4

    # straightness — gap analysis on top 3 cards
    t.high_card = max(vals)
    if len(vals) >= 3:
        top3 = sorted(vals)[-3:]
        spread = top3[-1] - top3[0]
        if spread <= 4:
            t.straight_possible = True
            t.connectedness = max(0.0, 1.0 - spread / 5.0)
        else:
            t.connectedness = 0.0
    elif len(vals) == 2:
        spread = abs(vals[1] - vals[0])
        t.connectedness = max(0.0, 1.0 - spread / 5.0)

    # wet score: weighted combo of two-tone + connected + paired-not-trips
    wet = 0.0
    if t.two_tone: wet += 0.35
    if t.monotone: wet += 0.55
    wet += 0.4 * t.connectedness
    if t.paired and not t.trips: wet += 0.1
    t.wet_score = min(wet, 1.0)
    return t


def is_dry(t: BoardTexture) -> bool:
    return t.wet_score < 0.30
