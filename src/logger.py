"""One JSON line per decision to stderr — Day 2 patch fuel."""
import sys
import json
import time


def log_decision(gs, action, t0):
    rec = {
        "ts": round(time.time(), 3),
        "hand_id": gs.hand_id,
        "street": gs.street,
        "hole": gs.your_cards,
        "board": gs.community_cards,
        "pot": gs.pot,
        "stack": gs.your_stack,
        "owed": gs.amount_owed,
        "n_active": gs.n_active,
        "pos": gs.position,
        "spr": round(gs.spr, 2),
        "action": action,
        "ms": int((time.perf_counter() - t0) * 1000),
    }
    try:
        sys.stderr.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except Exception:
        pass
