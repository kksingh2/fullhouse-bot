# fullhouse bot

my entry for the fullhouse 2026 poker hackathon (no-limit hold'em).

the engine calls `decide(game_state)` and you have to return an action (fold, check, call or raise). submission is the single file `bot.py`.

the bot:

- preflop: plays a tight range based on position. raise with strong hands, fold weak ones.
- postflop: uses eval7 (a poker hand library) to estimate how often my hand wins, then bets when ahead and folds or checks when behind.
- has a safety net: if anything goes wrong it just folds, so it never crashes out of a hand.

## run locally

```
pip install eval7
python bot.py
```

(the engine itself is at uzlez/fullhouse-engine if you want to play matches against the reference bots.)
