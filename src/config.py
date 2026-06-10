"""Typed config loader. Loads config.yaml once at module import."""
import os
import yaml
from types import SimpleNamespace


def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_ns(x) for x in d]
    return d


def load_config(path: str = None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    cfg = _ns(raw)

    # Apply mode-based overrides so Day 2 patch is one-line.
    mode = getattr(cfg, "mode", "qualify")
    if mode == "bracket":
        cfg.postflop.cbet_freq_dry = 0.78
        cfg.preflop.threebet_bluff_freq = 0.08
        cfg.preflop.squeeze_freq = 0.13
        cfg.sizing.max_bet_size_pot = 1.50
        cfg.sizing.overbet_river_polar = True
        cfg.stack_off.allin_threshold_equity = 0.72
        cfg.defense.mdf_buffer = 0.02
        cfg.exploit.min_hands_per_villain = 15
        cfg.exploit.deviation_cap_pp = 25
        cfg.mixing.jitter_close_decisions = 0.10
    elif mode == "bracket_underdog":
        cfg.postflop.cbet_freq_dry = 0.80
        cfg.preflop.threebet_bluff_freq = 0.12
        cfg.preflop.squeeze_freq = 0.16
        cfg.sizing.max_bet_size_pot = 2.00
        cfg.sizing.overbet_river_polar = True
        cfg.stack_off.allin_threshold_equity = 0.65
        cfg.defense.mdf_buffer = -0.03
        cfg.exploit.min_hands_per_villain = 10
        cfg.exploit.deviation_cap_pp = 35
        cfg.mixing.jitter_close_decisions = 0.05
    return cfg
