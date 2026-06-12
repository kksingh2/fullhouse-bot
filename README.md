# fullhouse bot

a poker bot i wrote for a poker hackathon (fullhouse 2026, sponsored by quadrature capital).

the way the hackathon works: you upload one python file. the organisers then run it in a tournament against everyone else's bots. each time its my bot's turn at the table, the engine calls my `decide` function and i have to return what to do (fold, check, call, or raise).

how the bot decides:

- **before the flop** (when only my own two cards are dealt): it follows a tight set of hands. raise with the strong ones, fold the weak ones. which hands count as strong depends on where i am sitting at the table.
- **after the flop** (when community cards are out): it uses a python library called eval7 to estimate how often my hand wins by simulating the rest of the hand many times. if im likely ahead it bets, if im likely behind it folds or just checks.
- **safety net**: if anything in the code breaks, it just folds that hand. so my bot never crashes out of the tournament.

## run

```
pip install eval7
python bot.py
```

(the official engine is at uzlez/fullhouse-engine. you can clone it locally and play matches between bots.)
