# Fullhouse Bot

My entry for the Fullhouse 2026 poker hackathon, a No-Limit Texas Hold'em bot. The whole bot is one file, `bot.py`, which is all you upload to the competition.

## How the game talks to the bot

The competition engine runs the bot in a tournament against everyone else's bots. Every time it is my bot's turn, the engine calls one function, `decide(game_state)`, and passes in everything about the current hand: my two cards, the shared cards on the table, the pot size, and what everyone has done so far. My function has to return one action: fold, check, call, or raise.

## How the bot decides

**Before the flop** (when only my own two cards are dealt): the bot looks up my hand in a table of opening ranges. Strong hands get raised, weak hands get folded, and how strict it is depends on where I am sitting at the table. Acting last is a big advantage, so the bot plays more hands from late positions.

**After the flop** (once shared cards appear): the bot stops using a table. It uses a library called `eval7` to deal out the rest of the hand thousands of times and count how often I would win. That win percentage is my "equity". If I am likely ahead, it bets; if behind, it checks or folds.

**Safety:** the bot has one firm rule. It will not put a lot of chips at risk unless it actually has a strong made hand, because an opponent betting big usually has something good. And if any code ever errors, it just folds, so the bot can never crash out of the tournament.

## Files

- `bot.py` is the complete bot and the only file submitted.
- `src/` holds the earlier, multi-file version I built first, before folding everything into the single file.

## Run it

```
pip install eval7
python bot.py
```

The official engine is at `uzlez/fullhouse-engine` if you want to run full matches against the reference bots.
