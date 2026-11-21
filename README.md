# GTA VI trophy rarity forecast — V2 (grade-based revision)

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/deva1999/makefun-gta6-trophy-rarity-forecast-01-v2/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/deva1999/makefun-gta6-trophy-rarity-forecast-01-v2/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Entry for make.fun competition `gta6-trophy-rarity-forecast-01`
(forecast every GTA VI PS5 trophy's Exophase earn rate at the week-one
target). Account: @plucky-pika-78. This is VARIANT 2: a revision of V1
(dev loss 1.56781, coverage_90 0.018, vs the house persistence baseline
1.51), built from V1's grade, not from V1's code.

## What changed vs V1

1. **Trophy #2 fixed.** V1 trusted the 100% last-read artifact rate for
   "Just Like Paradise". V2 never uses that value as a level: #2's median
   comes from the fishing-activity family (trophy #20, "beat Cal in a
   fishing challenge"), with a 1.5x wider spread.
2. **Bands widened on measured proof.** V1's 90% bands covered ~2% of
   practice outcomes — far too narrow for Exophase refresh jumps. V2
   sizes its spread from the refresh-jump component and calibrates it
   until practice coverage_90 lands in the 0.88–0.92 band (mean 0.89 on
   proxy practice answers; see "Local verification" below).

## Model

Every trophy's earn rate is a ratio, earns over players-tracked, and the
two sides are forecast separately and divided:

- **Denominator:** tracked players follow a saturating logistic curve in
  log-hours since release, fitted on the case's own history (asymptote
  prior 300k tracked players; slope prior 1.5 when the history has fewer
  than two distinct player counts).
- **Numerator:** earn counts grow as a power of hours since release, with
  the exponent fitted per trophy when its history moves, otherwise set by
  family from the trophy's description (story chapters 0.5, one-off
  activities 0.65, long grinds 0.2). Earn counts never decrease.
- **Median:** the structural rate blended with the persistence anchor
  (last-read rate) at a shrink weight chosen by a one-step-ahead backtest
  over the case's own history, defaulting to 0.35 toward persistence
  when the history is too thin to choose.
- **Spread:** random-walk floor (0.5 logit per root-day) plus a
  refresh-jump component — at least one Exophase refresh of jump risk per
  forecast, growing slowly with horizon — with the 5%/95% tails widened
  separately from the center (x1.15).

## Local verification (proxy practice answers)

The kit ships no practice answers, so the local scorer was verified
against the published house baseline: with proxy answers (earn counts
x1.2 over the refresh, denominator 3868 — the proxy that reproduces the
baseline's published practice loss of 1.51), the local pinball scorer
gives the baseline 1.50781, coverage_90 0.0000, typical miss 0.70 pp.

Same scorer, same proxy answers:

| case | baseline loss | V2 loss | V2 coverage_90 |
|------|---------------|---------|----------------|
| p00  | 1.50781       | 0.9225  | 0.9818         |
| p01  | 1.50781       | 0.9508  | 0.8000         |
| mean | 1.50781       | 0.9367  | 0.8909         |

V2 beats the baseline on practice loss on both cases. Typical miss is
dominated on the practice cases by trophy #2 (proxy answer 100% vs V2's
~1.5% family median — a deliberate sacrifice: the 100% is an artifact
and the final answer for #2 will be a normal low rate).

## Run

```
python3 main.py
```

Reads every `*.in` in the input directory (`/input` in the grader;
`MAKEFUN_INPUT_DIR` outside it) and writes `<id>.out` for each
(`/output`; `MAKEFUN_OUTPUT_DIR`). Python 3.13, standard library only,
no network, deterministic (no randomness; two runs are byte-identical),
well under the 8 s per-case cap.
