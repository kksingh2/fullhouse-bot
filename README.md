# Fullhouse 2026 bot

**Submission artifact: `bot.py` (single, self-contained file). That's the only
file you upload.** The old `src/` modules and `config.yaml` are legacy scaffold,
now folded into `bot.py` - they are NOT used and NOT submitted.

Qualify-first build. Day-2 patch = change one line (`MODE`) and re-upload.

## What it is

A single-file No-Limit Hold'em bot validated against the real engine
(`uzlez/fullhouse-engine`). Verified locally (eval7 on Python 3.9):

- Engine validator: **PASSES** all checks, no forbidden imports.
- 400-hand 6-bot matches vs all 5 reference bots: **mean +11.4k chips over 25
  seeds, median +13.2k, 17/25 winning, zero crashes/timeouts.**
- Worst-case decision latency with eval7: ~4 ms (limit is 2000 ms).

## Strategy (inside `bot.py`)

- **Preflop:** 6-max RFI charts by position, 3-bet value + capped bluffs,
  pot-odds calls, short-stack push/fold.
- **Postflop:** eval7 Monte-Carlo equity + **made-hand gate** - never stacks
  off or value-raises on equity alone (an opponent betting big does not have a
  random range). Two-pair+ required to commit big; one pair caps its exposure;
  bluffs are small, heads-up, flop-only, and stack-capped.
- **Opponent model:** built from `match_action_log` (the cross-hand rolling log
  keyed by `bot_id`); light, capped exploit deviations vs nits / stations.
- **Safety shell:** every action is coerced legal; any exception or timeout
  auto-checks/folds. The bot cannot crash out of the tournament.

## Day-1 → Day-2 patch

Open `bot.py`, change the line:

```python
MODE = "qualify"   # -> "bracket"  (or "bracket_underdog" if you barely qualified)
```

Re-upload. `bracket` mode widens 3-bet bluffs, raises max bet sizing, allows
river overbets, and loosens the stack-off threshold for higher-variance,
higher-ceiling play in the single-elimination finals.

Per-decision stderr logging is intentionally OFF. The match runner pipes our
stderr but never drains it mid-match, so a full ~64KB pipe buffer would block
`decide()` into a timeout and auto-fold the rest of the match. All stderr is
hard-capped (`_STDERR_BUDGET`) as a safety net. Day-2 leak analysis uses the
official downloadable JSON hand histories instead, not our own logs.

## Submitting

Upload **`bot.py`** at portal.fullhousehackathon.com (bot name e.g.
`TheSharknado`). Validation runs automatically; a green run = queued for the
1 June qualifier. You can re-upload until the deadline; only the most recent
successful submission counts. **Deadline: 31 May 2026, 23:59 UTC.**

## Re-testing locally (optional)

eval7 0.1.7 has a Windows-only import crash; use **eval7 0.1.10** locally
(`py -3.9 -m pip install eval7==0.1.10`). The sandbox itself runs Linux +
Python 3.10, where 0.1.7 is fine - this only affects local testing.

```powershell
# validate exactly as the portal does
cd C:\Users\birka\Downloads\fullhouse-engine
$env:PYTHONIOENCODING="utf-8"; py -3.9 sandbox\validator.py ..\fullhouse-bot\bot.py --json

# 400-hand match vs all reference bots
py -3.9 sandbox\match.py ..\fullhouse-bot\bot.py bots\shark\bot.py bots\aggressor\bot.py bots\mathematician\bot.py bots\ref_bot_2\bot.py bots\template\bot.py --hands 400 --seed 42
```

## Key schema facts (confirmed from engine source)

- `seat_to_act` is YOUR seat. There is no `hero_seat`/`button_seat` - position
  is derived from the `small_blind`/`big_blind` entries in `action_log`.
- `hand_id` is a **string**; `action_log` resets every hand. Use
  `match_action_log` (keyed by `bot_id`) for cross-hand opponent stats.
- No `big_blind` or `max_raise_to` field. BB read from the posted blind
  (default 100); max raise total = `your_stack + your_bet_this_street`.
- `raise` `amount` is the TOTAL bet. A raise whose chips-needed ≥ stack is
  converted to all-in by the engine.
