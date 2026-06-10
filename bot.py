"""Fullhouse Hackathon 2026 — single-file, sandbox-safe poker bot.

Engine calls decide(game_state: dict) -> dict, once per action, 2s deadline.
Auto-folds on crash or timeout; bot stays in the tournament.

SCHEMA (authoritative, from uzlez/fullhouse-engine engine/game.py::_build_state):
  type                 "action_request" | "warmup" | "hand_complete"
  hand_id              str  (e.g. "local_ab12_h0007")  -- NOT an int
  street               "preflop"|"flop"|"turn"|"river"
  seat_to_act          int  -- THIS IS MY SEAT
  pot                  int
  community_cards      list[str]
  current_bet          int  -- highest total bet this street
  min_raise_to         int  -- minimum legal raise TOTAL
  amount_owed          int  -- chips to call (0 => can check)
  can_check            bool
  your_cards           list[str]
  your_stack           int  -- chips behind (already-bet chips are NOT here)
  your_bet_this_street int
  players              list[{seat,bot_id,stack,state,is_folded,is_all_in,
                             bet_this_street,hole_cards}]
  action_log           list[{seat,action,amount}]  -- THIS HAND ONLY; resets each
                       hand; includes "small_blind"/"big_blind" entries
  match_action_log     list[{hand_num,seat,bot_id,action,amount}]  -- cross-hand,
                       rolling (<=200), present only via match.py (not validator).
                       Keyed by bot_id (stable; seats are re-indexed per hand).

CONSTANTS: SMALL_BLIND=50, BIG_BLIND=100, STARTING_STACK=10000.
A raise whose chips-needed >= your_stack is converted to all_in by the engine,
so the maximum legal raise TOTAL is your_stack + your_bet_this_street.

SANDBOX: Python 3.10. Pre-installed: eval7, numpy, scipy, treys, scikit-learn.
No pyyaml. Banned (validator AST-rejects): socket/urllib/requests/http, subprocess,
multiprocessing, threading, asyncio, pickle, shelve, ctypes, runpy, importlib,
and calls __import__/eval/exec/compile/os.system/os.popen/... . NONE used here.
"""
import sys
import json
import time
import random
import traceback
from types import SimpleNamespace

try:
    import eval7  # type: ignore
    _HAS_EVAL7 = True
except Exception:
    _HAS_EVAL7 = False

# The match runner spawns us with stderr=PIPE and never drains it during a
# match. A full OS pipe buffer (~64KB on Linux) makes the next write() BLOCK,
# which would hang decide() into a 2s timeout -> auto-fold every remaining
# hand. So we hard-cap total stderr bytes and stop writing well before that.
_STDERR_BUDGET = 16 * 1024
_stderr_written = 0


def _safe_stderr(msg):
    """Write to stderr at most until the byte budget is exhausted. Never raises."""
    global _stderr_written
    if _stderr_written >= _STDERR_BUDGET:
        return
    try:
        data = msg if msg.endswith("\n") else msg + "\n"
        _stderr_written += len(data)
        sys.stderr.write(data)
        sys.stderr.flush()
    except Exception:
        pass

BIG_BLIND_DEFAULT = 100


# =============================================================================
# CONFIG  (Day-2 patch: change MODE only, re-upload)
# =============================================================================
MODE = "qualify"   # "qualify" | "bracket" | "bracket_underdog"

_BASE_CONFIG = {
    "mode": MODE,
    "timing": {"hard_deadline_ms": 1500, "mc_flop": 500, "mc_turn": 400, "mc_river": 300},
    "preflop": {
        "open_size_bb": 2.5,
        "threebet_size_xpot": 3.0,
        "threebet_bluff_freq": 0.06,
        "push_fold_threshold_bb": 12,
        "call_eq_margin": 0.04,
    },
    "postflop": {
        "cbet_freq_dry": 0.65,
        "cbet_freq_wet": 0.40,
        "cbet_size_dry_xpot": 0.40,
        "cbet_size_wet_xpot": 0.66,
        "value_bet_eq": 0.60,
    },
    "sizing": {"max_bet_size_pot": 1.00, "overbet_river_polar": False},
    "stack_off": {"allin_threshold_equity": 0.80},
    "defense": {"mdf_buffer": 0.05},
    "exploit": {
        "enabled": True,
        "min_hands_per_villain": 25,
        "deviation_cap_pp": 12,
    },
    "mixing": {"jitter": 0.0},
    "logging": {"log_every_decision": False},
}


def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_ns(x) for x in d]
    return d


def _load_config():
    cfg = _ns(_BASE_CONFIG)
    mode = getattr(cfg, "mode", "qualify")
    if mode == "bracket":
        cfg.postflop.cbet_freq_dry = 0.74
        cfg.preflop.threebet_bluff_freq = 0.10
        cfg.sizing.max_bet_size_pot = 1.50
        cfg.sizing.overbet_river_polar = True
        cfg.stack_off.allin_threshold_equity = 0.72
        cfg.defense.mdf_buffer = 0.02
        cfg.exploit.min_hands_per_villain = 15
        cfg.exploit.deviation_cap_pp = 25
    elif mode == "bracket_underdog":
        cfg.postflop.cbet_freq_dry = 0.80
        cfg.preflop.threebet_bluff_freq = 0.14
        cfg.sizing.max_bet_size_pot = 2.00
        cfg.sizing.overbet_river_polar = True
        cfg.stack_off.allin_threshold_equity = 0.64
        cfg.defense.mdf_buffer = -0.03
        cfg.exploit.min_hands_per_villain = 10
        cfg.exploit.deviation_cap_pp = 35
    return cfg


CONFIG = _load_config()


# =============================================================================
# HAND EVALUATION  (169-bucket LUT + eval7 Monte-Carlo)
# =============================================================================
RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}


def hand_169(hole):
    """Canonical bucket: ['Ah','Kd']->'AKo', ['As','Ks']->'AKs', ['7c','7h']->'77'."""
    if not hole or len(hole) != 2 or len(hole[0]) < 2 or len(hole[1]) < 2:
        return None
    r1, s1 = hole[0][0], hole[0][1]
    r2, s2 = hole[1][0], hole[1][1]
    if r1 not in RANK_VAL or r2 not in RANK_VAL:
        return None
    if RANK_VAL[r1] < RANK_VAL[r2]:
        r1, r2, s1, s2 = r2, r1, s2, s1
    if r1 == r2:
        return r1 + r2
    return r1 + r2 + ("s" if s1 == s2 else "o")


# Heads-up equity vs a random hand (PokerStove values), used preflop and as a
# fallback whenever eval7 is unavailable.
PREFLOP_EQUITY_VS_RANDOM = {
    "AA": 0.852, "KK": 0.824, "QQ": 0.799, "JJ": 0.775, "TT": 0.751,
    "99": 0.720, "88": 0.691, "77": 0.661, "66": 0.633, "55": 0.605,
    "44": 0.578, "33": 0.549, "22": 0.503,
    "AKs": 0.671, "AQs": 0.663, "AJs": 0.654, "ATs": 0.645, "A9s": 0.629,
    "A8s": 0.620, "A7s": 0.610, "A6s": 0.598, "A5s": 0.601, "A4s": 0.594,
    "A3s": 0.585, "A2s": 0.576,
    "KQs": 0.631, "KJs": 0.621, "KTs": 0.611, "K9s": 0.589, "K8s": 0.567,
    "K7s": 0.557, "K6s": 0.547, "K5s": 0.536, "K4s": 0.526, "K3s": 0.517, "K2s": 0.508,
    "QJs": 0.601, "QTs": 0.592, "Q9s": 0.571, "Q8s": 0.549, "Q7s": 0.527,
    "Q6s": 0.518, "Q5s": 0.508, "Q4s": 0.498, "Q3s": 0.488, "Q2s": 0.479,
    "JTs": 0.581, "J9s": 0.561, "J8s": 0.539, "J7s": 0.518, "J6s": 0.487,
    "J5s": 0.477, "J4s": 0.467, "J3s": 0.458, "J2s": 0.449,
    "T9s": 0.541, "T8s": 0.520, "T7s": 0.499, "T6s": 0.479, "T5s": 0.448,
    "T4s": 0.439, "T3s": 0.430, "T2s": 0.420,
    "98s": 0.500, "97s": 0.480, "96s": 0.460, "95s": 0.430, "94s": 0.398,
    "93s": 0.389, "92s": 0.380,
    "87s": 0.461, "86s": 0.441, "85s": 0.412, "84s": 0.382, "83s": 0.354, "82s": 0.345,
    "76s": 0.424, "75s": 0.404, "74s": 0.376, "73s": 0.347, "72s": 0.338,
    "65s": 0.388, "64s": 0.369, "63s": 0.341, "62s": 0.332,
    "54s": 0.359, "53s": 0.341, "52s": 0.321,
    "43s": 0.327, "42s": 0.310, "32s": 0.296,
    "AKo": 0.652, "AQo": 0.644, "AJo": 0.633, "ATo": 0.622, "A9o": 0.604,
    "A8o": 0.594, "A7o": 0.584, "A6o": 0.572, "A5o": 0.575, "A4o": 0.567,
    "A3o": 0.558, "A2o": 0.549,
    "KQo": 0.611, "KJo": 0.601, "KTo": 0.589, "K9o": 0.564, "K8o": 0.541,
    "K7o": 0.531, "K6o": 0.520, "K5o": 0.508, "K4o": 0.498, "K3o": 0.489, "K2o": 0.480,
    "QJo": 0.580, "QTo": 0.570, "Q9o": 0.546, "Q8o": 0.521, "Q7o": 0.499,
    "Q6o": 0.488, "Q5o": 0.479, "Q4o": 0.468, "Q3o": 0.458, "Q2o": 0.448,
    "JTo": 0.560, "J9o": 0.537, "J8o": 0.512, "J7o": 0.488, "J6o": 0.456,
    "J5o": 0.446, "J4o": 0.436, "J3o": 0.426, "J2o": 0.417,
    "T9o": 0.519, "T8o": 0.495, "T7o": 0.471, "T6o": 0.449, "T5o": 0.415,
    "T4o": 0.406, "T3o": 0.397, "T2o": 0.387,
    "98o": 0.476, "97o": 0.453, "96o": 0.430, "95o": 0.397, "94o": 0.364,
    "93o": 0.355, "92o": 0.346,
    "87o": 0.434, "86o": 0.412, "85o": 0.379, "84o": 0.348, "83o": 0.330, "82o": 0.320,
    "76o": 0.396, "75o": 0.374, "74o": 0.343, "73o": 0.325, "72o": 0.305,
    "65o": 0.358, "64o": 0.337, "63o": 0.318,
    "54o": 0.327, "53o": 0.308, "52o": 0.295,
    "43o": 0.292, "42o": 0.280, "32o": 0.262,
}


def preflop_equity_vs_random(hole):
    return PREFLOP_EQUITY_VS_RANDOM.get(hand_169(hole), 0.40)


# Made-hand category (postflop). Higher = stronger. Used as a hard gate so we
# never stack off / value-raise on equity-vs-random alone (a betting opponent's
# range is NOT random — ace-high looks great vs random and terrible vs a raiser).
HAND_RANK = {
    "High Card": 0, "Pair": 1, "Two Pair": 2, "Trips": 3, "Straight": 4,
    "Flush": 5, "Full House": 6, "Quads": 7, "Straight Flush": 8,
}


def made_hand_rank(hole, board):
    """0=high card .. 8=straight flush. -1 if eval7 unavailable / bad input."""
    if not _HAS_EVAL7 or len(board) < 3 or len(hole) != 2:
        return -1
    try:
        score = eval7.evaluate([eval7.Card(c) for c in hole + board])
        return HAND_RANK.get(str(eval7.handtype(score)), 0)
    except Exception:
        return -1


def equity_montecarlo(hole, board, n_villains, trials, deadline_s):
    """eval7 Monte-Carlo equity vs n_villains random hands. LUT fallback."""
    if not _HAS_EVAL7 or n_villains < 1:
        base = preflop_equity_vs_random(hole)
        return base ** max(n_villains, 1)
    try:
        hero = [eval7.Card(c) for c in hole]
        bd = [eval7.Card(c) for c in board]
        dead = set(str(c) for c in hero + bd)
        deck = [eval7.Card(r + s) for r in RANKS for s in "shdc" if (r + s) not in dead]
        need_board = 5 - len(bd)
        need = need_board + 2 * n_villains
        if need > len(deck):
            return 0.5
        wins = ties = 0
        i = 0
        for i in range(trials):
            if deadline_s is not None and time.perf_counter() > deadline_s - 0.05:
                break
            sample = random.sample(deck, need)
            full_board = bd + sample[:need_board]
            hero_score = eval7.evaluate(hero + full_board)
            off = need_board
            best_v = -1
            for _v in range(n_villains):
                vh = sample[off:off + 2]
                off += 2
                vs = eval7.evaluate(vh + full_board)
                if vs > best_v:
                    best_v = vs
            if hero_score > best_v:
                wins += 1
            elif hero_score == best_v:
                ties += 1
        n = max(i + 1, 1)
        return (wins + 0.5 * ties) / n
    except Exception:
        return preflop_equity_vs_random(hole)


# =============================================================================
# PREFLOP RANGES (6-max, encoded as 169-bucket sets)
# =============================================================================
def _expand(spec):
    out = set()
    spec = spec.strip()
    if "-" in spec:  # e.g. "K9s-K6s"
        a, b = spec.split("-")
        if len(a) == 3 and len(b) == 3 and a[0] == b[0] and a[2] == b[2]:
            hi, suit = a[0], a[2]
            i1, i2 = RANK_VAL[a[1]], RANK_VAL[b[1]]
            for i in range(min(i1, i2), max(i1, i2) + 1):
                out.add(hi + RANKS[i] + suit)
            return out
    if spec.endswith("+"):
        body = spec[:-1]
        if len(body) == 2 and body[0] == body[1]:        # "22+"
            for j in range(RANK_VAL[body[0]], len(RANKS)):
                out.add(RANKS[j] + RANKS[j])
            return out
        if len(body) == 3:                                # "A2s+", "K9o+"
            hi, lo, suit = body[0], body[1], body[2]
            for j in range(RANK_VAL[lo], RANK_VAL[hi]):
                out.add(hi + RANKS[j] + suit)
            return out
    out.add(spec)
    return out


def _build(*specs):
    out = set()
    for s in specs:
        out |= _expand(s)
    return out


RFI = {
    "UTG": _build("22+", "ATs+", "KTs+", "QTs+", "JTs", "T9s", "98s", "AJo+", "KQo"),
    "MP":  _build("22+", "A8s+", "K9s+", "Q9s+", "J9s+", "T9s", "98s", "87s", "ATo+", "KJo+", "QJo"),
    "CO":  _build("22+", "A2s+", "K7s+", "Q8s+", "J8s+", "T8s+", "97s+", "86s+", "75s+", "65s", "ATo+", "KTo+", "QTo+", "JTo"),
    "BTN": _build("22+", "A2s+", "K2s+", "Q4s+", "J6s+", "T6s+", "96s+", "85s+", "74s+", "64s+", "53s+", "A2o+", "K8o+", "Q9o+", "J9o+", "T8o+", "98o", "87o", "76o"),
    "SB":  _build("22+", "A2s+", "K3s+", "Q6s+", "J7s+", "T7s+", "97s+", "86s+", "75s+", "64s+", "54s", "A4o+", "K9o+", "Q9o+", "J9o+", "T9o", "98o"),
}
RFI_DEFAULT = RFI["CO"]   # used when position unknown

THREEBET_VALUE = _build("QQ+", "AKs", "AKo", "AQs")
THREEBET_BLUFF = _build("A5s", "A4s", "A3s", "K9s", "Q9s", "J9s", "T9s", "98s", "76s", "65s")
CALL_VS_RAISE = _build("22+", "ATs+", "KTs+", "QTs+", "JTs", "T9s", "98s", "AQo+", "KQo", "AJs", "KJs")

PUSH_RANGES = {
    12: _build("22+", "A2s+", "A8o+", "K9s+", "KTo+", "Q9s+", "QJo", "J9s+", "JTo", "T9s"),
    9:  _build("22+", "A2s+", "A5o+", "K7s+", "K9o+", "Q9s+", "QTo+", "J8s+", "JTo", "T8s+", "98s"),
    6:  _build("22+", "A2s+", "A2o+", "K2s+", "K7o+", "Q5s+", "Q9o+", "J7s+", "J9o+", "T7s+", "97s+", "87s", "76s"),
}


def push_range(bb):
    chosen = PUSH_RANGES[12]
    for thr in sorted(PUSH_RANGES):
        if bb <= thr:
            return PUSH_RANGES[thr]
    return chosen


# =============================================================================
# BOARD TEXTURE
# =============================================================================
def board_wetness(community):
    """0 (dry) .. 1 (wet). Robust to short/odd inputs."""
    if not community or len(community) < 3:
        return 0.0
    try:
        ranks = [c[0] for c in community]
        suits = [c[1] for c in community]
        vals = sorted(RANK_VAL[r] for r in ranks)
    except (KeyError, IndexError, TypeError):
        return 0.3
    suit_counts = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1
    max_suit = max(suit_counts.values())
    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    paired = max(rank_counts.values()) >= 2
    top3 = vals[-3:]
    span = top3[-1] - top3[0] if len(top3) >= 2 else 99
    connected = span <= 4
    wet = 0.0
    if max_suit >= 3:
        wet += 0.45
    elif max_suit == 2:
        wet += 0.22
    if connected:
        wet += 0.30
    if sum(1 for v in vals if v >= RANK_VAL["T"]) >= 2:
        wet += 0.12
    if paired:
        wet -= 0.10
    return max(0.0, min(1.0, wet))


# =============================================================================
# STATE  (parse the engine dict into a thin typed view)
# =============================================================================
def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class State(object):
    def __init__(self, raw):
        if not isinstance(raw, dict):
            raw = {}
        self.raw = raw
        self.hand_id = str(raw.get("hand_id", ""))
        self.street = str(raw.get("street", "preflop")).lower()
        self.my_seat = _int(raw.get("seat_to_act", -1), -1)
        self.pot = _int(raw.get("pot", 0))
        self.my_cards = list(raw.get("your_cards", []) or [])
        self.community = list(raw.get("community_cards", []) or [])
        self.current_bet = _int(raw.get("current_bet", 0))
        self.min_raise_to = _int(raw.get("min_raise_to", 0))
        self.amount_owed = _int(raw.get("amount_owed", 0))
        self.can_check = bool(raw.get("can_check", self.amount_owed == 0))
        self.my_stack = _int(raw.get("your_stack", 0))
        self.my_bet_street = _int(raw.get("your_bet_this_street", 0))
        self.players = list(raw.get("players", []) or [])
        self.action_log = list(raw.get("action_log", []) or [])
        self.match_log = list(raw.get("match_action_log", []) or [])

        # Big blind: read the posted big_blind from this hand's log, else default.
        bb = BIG_BLIND_DEFAULT
        for e in self.action_log:
            if isinstance(e, dict) and e.get("action") == "big_blind":
                bb = _int(e.get("amount", bb), bb) or bb
                break
        self.big_blind = bb if bb > 0 else BIG_BLIND_DEFAULT

        # Max legal raise TOTAL = stack behind + already committed this street.
        self.max_raise_to = self.my_stack + self.my_bet_street

        # Opponents still in the hand (not folded, not me).
        self.n_villains = 0
        for p in self.players:
            if not isinstance(p, dict):
                continue
            if p.get("seat") == self.my_seat:
                continue
            if p.get("is_folded") or p.get("state") == "folded":
                continue
            self.n_villains += 1
        if self.n_villains < 1:
            self.n_villains = 1

    @property
    def n_seats(self):
        return max(len(self.players), 2)

    @property
    def position(self):
        """6-max label by offset from the button. 'UNK' if blinds not in log."""
        n = self.n_seats
        sb = bb = None
        for e in self.action_log:
            if not isinstance(e, dict):
                continue
            if e.get("action") == "small_blind":
                sb = _int(e.get("seat", -1), -1)
            elif e.get("action") == "big_blind":
                bb = _int(e.get("seat", -1), -1)
        if bb is None or self.my_seat < 0:
            return "UNK"
        if n == 2:
            dealer = (bb - 1) % n     # heads-up: dealer == SB
        else:
            dealer = (bb - 2) % n
        offset = (self.my_seat - dealer) % n
        names = {
            6: ["BTN", "SB", "BB", "UTG", "MP", "CO"],
            5: ["BTN", "SB", "BB", "UTG", "CO"],
            4: ["BTN", "SB", "BB", "CO"],
            3: ["BTN", "SB", "BB"],
            2: ["BTN", "BB"],
        }.get(n)
        if not names or offset >= len(names):
            return "UNK"
        return names[offset]


# =============================================================================
# OPPONENT MODEL  (stateless: derived from match_action_log keyed by bot_id)
# =============================================================================
def build_opponent_stats(match_log):
    """Return {bot_id: {'hands','vpip','pfr','aff'}} from the rolling match log."""
    stats = {}
    hands_seen = {}
    for e in match_log:
        if not isinstance(e, dict):
            continue
        bid = e.get("bot_id")
        action = e.get("action")
        hand = e.get("hand_num")
        if bid is None or action is None:
            continue
        s = stats.setdefault(bid, {"vpip_y": 0, "vpip_n": 0, "pfr_y": 0,
                                   "agg": 0, "passive": 0, "_hands": set()})
        s["_hands"].add(hand)
        if action in ("raise", "all_in", "bet"):
            s["agg"] += 1
            s["pfr_y"] += 1
            s["vpip_y"] += 1
        elif action == "call":
            s["passive"] += 1
            s["vpip_y"] += 1
        elif action == "check":
            s["passive"] += 1
        elif action == "fold":
            s["vpip_n"] += 1
    out = {}
    for bid, s in stats.items():
        n = len(s["_hands"])
        vp = s["vpip_y"] + s["vpip_n"]
        out[bid] = {
            "hands": n,
            "vpip": s["vpip_y"] / vp if vp else 0.3,
            "pfr": s["pfr_y"] / vp if vp else 0.15,
            "aff": s["agg"] / max(s["passive"], 1),
        }
    return out


def classify(st):
    if st["hands"] < 8:
        return "unknown"
    v, a = st["vpip"], st["aff"]
    if v > 0.45 and a > 2.5:
        return "maniac"
    if v > 0.42 and a < 1.2:
        return "station"
    if v < 0.16:
        return "nit"
    if v > 0.32 and a > 1.8:
        return "lag"
    return "reg"


def last_aggressor_bot_id(s):
    """bot_id of the most recent raiser/bettor this hand (an opponent)."""
    seat_to_bid = {}
    for p in s.players:
        if isinstance(p, dict):
            seat_to_bid[p.get("seat")] = p.get("bot_id")
    for e in reversed(s.action_log):
        if not isinstance(e, dict):
            continue
        if e.get("action") in ("raise", "bet", "all_in"):
            seat = e.get("seat")
            if seat != s.my_seat:
                return seat_to_bid.get(seat)
    return None


# =============================================================================
# STRATEGY
# =============================================================================
def _raise_to(s, target):
    """Clamp a desired TOTAL bet to a legal raise, escalating to all_in at cap."""
    target = int(target)
    floor = s.min_raise_to if s.min_raise_to > 0 else (s.current_bet + s.big_blind)
    target = max(target, floor)
    if target >= s.max_raise_to:
        return {"action": "all_in"}
    return {"action": "raise", "amount": target}


def decide_preflop(s, cfg):
    bucket = hand_169(s.my_cards)
    pos = s.position
    eff_bb = s.my_stack / max(s.big_blind, 1)
    facing_raise = s.current_bet > s.big_blind

    # Short-stack push/fold.
    if eff_bb <= cfg.preflop.push_fold_threshold_bb and bucket:
        if bucket in push_range(int(eff_bb)):
            return {"action": "all_in"}
        if not facing_raise and s.can_check:
            return {"action": "check"}
        return {"action": "fold"}

    if facing_raise:
        # PREMIUMS: the only hands worth getting 100bb in preflop.
        premium = bucket in ("AA", "KK", "QQ", "AKs", "AKo") if bucket else False
        # How much of our stack are we being asked to commit right now?
        commit_frac = s.amount_owed / max(s.my_stack + s.my_bet_street, 1)
        # A "big" preflop price = a re-raise/4-bet/shove, not just calling an open.
        big_price = s.current_bet > s.big_blind * 4 or commit_frac >= 0.25

        if premium:
            # Re-raise; if it gets jammed on, we're happy to get it in.
            if commit_frac >= 0.6 or s.amount_owed >= s.my_stack * 0.6:
                return {"action": "all_in"}
            return _raise_to(s, max(s.current_bet * 3, s.min_raise_to))

        # CRITICAL FIX: getting all-in preflop with AQs/KQs/AK-light/pairs is a
        # coinflip, and each lost flip is a -10k bust that tanks the average.
        # Non-premiums NEVER stack off preflop — they fold to a big re-raise.
        if big_price:
            return {"action": "fold"}

        if bucket and bucket in THREEBET_VALUE:
            # 3-bet for value but to a controlled size, not committing.
            return _raise_to(s, max(s.current_bet * 3, s.min_raise_to))
        if (bucket and bucket in THREEBET_BLUFF
                and random.random() < cfg.preflop.threebet_bluff_freq):
            return _raise_to(s, max(s.current_bet * 3, s.min_raise_to))
        if bucket and bucket in CALL_VS_RAISE:
            eq = preflop_equity_vs_random(s.my_cards)
            need = s.amount_owed / max(s.pot + s.amount_owed, 1)
            if eq >= need + cfg.preflop.call_eq_margin:
                return {"action": "call"}
        return {"action": "fold"}

    # First-in / limped: open the position range, else take a free check or fold.
    open_range = RFI.get(pos, RFI_DEFAULT)
    if bucket and bucket in open_range:
        return _raise_to(s, s.big_blind * cfg.preflop.open_size_bb)
    if s.can_check:
        return {"action": "check"}
    return {"action": "fold"}


def decide_postflop(s, cfg, deadline_s):
    budget = {"flop": cfg.timing.mc_flop, "turn": cfg.timing.mc_turn,
              "river": cfg.timing.mc_river}.get(s.street, 300)
    eq = equity_montecarlo(s.my_cards, s.community, s.n_villains, budget, deadline_s)
    wet = board_wetness(s.community)
    made = made_hand_rank(s.my_cards, s.community)   # 0=high card .. 8=str.flush

    if s.amount_owed > 0:
        big_bet = s.amount_owed >= s.my_stack * 0.4
        need = s.amount_owed / max(s.pot + s.amount_owed, 1)
        # CRITICAL: equity_montecarlo is vs RANDOM hands, but a villain who is
        # BETTING has a much stronger range — and multiway, someone almost
        # always has it. Discount raw equity before trusting it to call:
        #   - a flat penalty for facing aggression (range > random)
        #   - an extra penalty per additional villain (compounding)
        #   - heavier on later streets, where ranges are most defined
        street_pen = {"flop": 0.06, "turn": 0.09, "river": 0.12}.get(s.street, 0.08)
        multiway_pen = 0.07 * max(s.n_villains - 1, 0)
        eq_eff = eq - street_pen - multiway_pen
        # Stack off only with two pair or better AND high RAW equity.
        if made >= 2 and eq >= cfg.stack_off.allin_threshold_equity and big_bet:
            return {"action": "all_in"}
        # Value-raise two-pair-plus only, and only for a non-committing bet.
        if made >= 2 and eq >= 0.72 and not big_bet:
            return _raise_to(s, int((s.pot + s.amount_owed) * 0.66))
        # Never commit a big bet without two pair+.
        if big_bet and made < 2:
            return {"action": "check"} if s.can_check else {"action": "fold"}
        # One pair or worse multiway: fold unless the price is tiny. Multiway
        # one-pair call-downs are the single biggest chip leak.
        if s.n_villains >= 2 and made < 2 and need > 0.18:
            return {"action": "check"} if s.can_check else {"action": "fold"}
        # One pair heads-up: only continue at a reasonable price with the
        # aggression-discounted equity, and never bloat the pot calling thin.
        if made == 1 and (need > 0.40 or eq_eff < need):
            return {"action": "check"} if s.can_check else {"action": "fold"}
        # General defense on discounted equity.
        if eq_eff >= need + cfg.defense.mdf_buffer:
            return {"action": "call"}
        return {"action": "check"} if s.can_check else {"action": "fold"}

    # No bet to face. Value-bet made hands; bluff only small, heads-up, on the
    # flop, with real backdoor/overcard equity, capped to a small slice of
    # stack so a missed bluff never threatens the stack.
    dry = wet < 0.30
    size_x = cfg.postflop.cbet_size_dry_xpot if dry else cfg.postflop.cbet_size_wet_xpot
    # Multiway, raise the bar: one pair is rarely a value bet into 2+ players.
    min_made = 1 if s.n_villains == 1 else 2
    min_eq = cfg.postflop.value_bet_eq + 0.06 * max(s.n_villains - 1, 0)
    if eq >= min_eq and made >= min_made:
        target = int(max(s.pot * size_x * cfg.sizing.max_bet_size_pot, s.big_blind))
        return _raise_to(s, target)
    freq = cfg.postflop.cbet_freq_dry if dry else cfg.postflop.cbet_freq_wet
    if (s.street == "flop" and s.n_villains == 1 and made <= 0
            and eq >= 0.45 and random.random() < freq):
        target = int(min(s.pot * 0.40, s.my_stack * 0.12))
        if s.big_blind <= target:
            return _raise_to(s, target)
    return {"action": "check"} if s.can_check else {"action": "fold"}


def exploit_adjust(action, s, cfg, opp_stats):
    if not cfg.exploit.enabled or not opp_stats:
        return action
    bid = last_aggressor_bot_id(s)
    if bid is None or bid not in opp_stats:
        return action
    st = opp_stats[bid]
    if st["hands"] < cfg.exploit.min_hands_per_villain:
        return action
    cap = cfg.exploit.deviation_cap_pp / 100.0
    arch = classify(st)
    act = action.get("action")

    # vs a nit who folds too much: turn a marginal fold into a steal/bluff-raise.
    if (arch == "nit" and act == "fold" and s.can_check is False
            and s.amount_owed <= s.big_blind * 1.5 and random.random() < cap):
        return _raise_to(s, max(s.min_raise_to, int(s.pot * 0.5)))
    # vs a calling station: don't bluff; downgrade thin bluff-raises to check/call.
    if arch == "station" and act == "raise":
        if s.amount_owed > 0:
            return {"action": "call"}
        if s.can_check:
            return {"action": "check"}
    return action


# =============================================================================
# SAFETY  (snap any action to a legal, well-formed one — never fold for free)
# =============================================================================
def coerce(action, s):
    if not isinstance(action, dict):
        return {"action": "check"} if s.can_check else {"action": "fold"}
    a = str(action.get("action", "fold")).lower()

    if a == "all_in":
        return {"action": "all_in"} if s.my_stack > 0 else (
            {"action": "check"} if s.can_check else {"action": "fold"})
    if a == "check":
        return {"action": "check"} if s.can_check else {"action": "fold"}
    if a == "call":
        if s.amount_owed <= 0:
            return {"action": "check"} if s.can_check else {"action": "fold"}
        return {"action": "call"}
    if a == "raise":
        amt = action.get("amount")
        try:
            amt = int(amt)
        except (TypeError, ValueError):
            amt = s.min_raise_to
        if amt >= s.max_raise_to:
            return {"action": "all_in"} if s.my_stack > 0 else (
                {"action": "check"} if s.can_check else {"action": "fold"})
        floor = s.min_raise_to if s.min_raise_to > 0 else s.current_bet + s.big_blind
        return {"action": "raise", "amount": max(amt, floor)}
    if a == "fold":
        return {"action": "check"} if s.can_check else {"action": "fold"}
    return {"action": "check"} if s.can_check else {"action": "fold"}


# =============================================================================
# ENTRY POINT
# =============================================================================
def decide(game_state):
    t0 = time.perf_counter()
    # Warm-up ping (engine discards the reply); also handles non-action requests.
    if isinstance(game_state, dict) and game_state.get("type") not in ("action_request", None):
        return {"action": "check"}
    try:
        s = State(game_state)
        deadline = t0 + CONFIG.timing.hard_deadline_ms / 1000.0
        if s.street == "preflop":
            action = decide_preflop(s, CONFIG)
        else:
            action = decide_postflop(s, CONFIG, deadline)
        try:
            opp = build_opponent_stats(s.match_log)
            action = exploit_adjust(action, s, CONFIG, opp)
        except Exception:
            pass  # exploit layer must never break the bot
        action = coerce(action, s)
        if CONFIG.logging.log_every_decision:
            _safe_stderr(json.dumps({
                "hand": s.hand_id, "street": s.street, "pos": s.position,
                "cards": s.my_cards, "act": action,
                "ms": round((time.perf_counter() - t0) * 1000, 1)}))
        return action
    except Exception:
        _safe_stderr(json.dumps({"event": "PANIC", "tb": traceback.format_exc()}))
        if isinstance(game_state, dict) and game_state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}
