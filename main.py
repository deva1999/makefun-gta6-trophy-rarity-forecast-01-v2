"""GTA VI trophy rarity forecast (make.fun gta6-trophy-rarity-forecast-01), V2.

Model, in one paragraph: every trophy's earn rate is a ratio, earns over
players-tracked, and the two sides are forecast separately and divided.
The denominator (tracked players) follows a saturating logistic curve in
log-hours since release, fitted on the case's own history. The numerator
(earn counts) grows as a power of hours since release, with the exponent
fitted per trophy when its history moves and otherwise set by the trophy's
family (story chapters and one-off activities progress faster than long
grinds). The structural rate is blended with the persistence anchor
(last-read rate) at a shrink weight chosen by a small backtest over the
case's own history, defaulting to 0.35 toward persistence when the history
is too thin to choose. Trophy #2's 100% last-read rate is an early-data
artifact: its median is taken from the fishing-activity family instead
(trophy #20, "beat Cal in a fishing challenge"), with a much wider spread,
and its 100% value is never used as a level. Spreads start from the house
random-walk floor (0.5 logit per root-day) and add a refresh-jump component:
every forecast carries at least one Exophase refresh worth of jump risk,
growing slowly with horizon, with tails widened separately from the center,
because a refresh moves every rate at once and narrow bands died on the
first refresh in the practice data.

Runs as `python3 /bot/main.py` (Python 3.13, standard library only, no
network, deterministic — no randomness anywhere). Reads every `*.in` in the
input directory and writes `<id>.out` for each. Outside the grader,
MAKEFUN_INPUT_DIR and MAKEFUN_OUTPUT_DIR stand in for /input and /output.
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Random-walk spread floor from the house baseline, logit per root-day.
RW_SIGMA = 0.5
# Refresh-jump spread: one Exophase refresh moves rates by roughly a logit
# unit (the practice window's single refresh multiplied the tracked-player
# denominator ~6x and cut rates to ~a fifth); every forecast carries at
# least one refresh of jump risk, growing slowly with horizon. Calibrated
# on the practice cases against proxy answers (earn counts x1.2 over the
# refresh, denominator 3868 — the proxy that reproduces the house
# baseline's published practice loss 1.51): JUMP_SIGMA 0.68 lands mean
# practice coverage_90 at 0.89 (p00 0.98, p01 0.80 — the uniform proxy
# makes per-case coverage a knife-edge, so the mean is the calibrated
# statistic), inside the 0.88-0.92 band; loss 0.92/0.95 vs baseline 1.51.
JUMP_SIGMA = 0.68
# Tails are sized separately from the center: refresh jumps are fat-tailed,
# so the 5%/95% levels get a wider sigma than the 25%/75% levels.
TAIL_WIDEN = 1.15
# Default shrink toward the persistence anchor when the case history is
# too thin to fit a weight by backtest.
SHRINK_DEFAULT = 0.35
# Week-one tracked-player scale prior (Exophase tracks a self-selected
# subset of PSN players; GTA V's long-run tracked base is in the 100k+
# range). Used only as the logistic asymptote, never as a level.
ASYMPTOTE_PLAYERS = 300000.0
# Log-log slope prior for tracked-player growth when the history has fewer
# than two distinct player counts (launch-night growth is superlinear in
# hours: early adopters link accounts faster than hours pass).
SLOPE_PRIOR = 1.5
# Earn-count growth exponents by trophy family, used when a trophy's own
# history is too thin to fit one (earn counts grow slower than the player
# base: joining is instant, finishing chapters takes hours).
EXPONENT_STORY = 0.5
EXPONENT_ONEOFF = 0.65
EXPONENT_GRIND = 0.2
# Trophy #2's artifact flag: a last-read rate at or above this is treated
# as an early-data artifact, never as a level.
ARTIFACT_RATE = 99.0


def clamp_pct(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(lg):
    return 100.0 / (1.0 + math.exp(-lg))


def round4(x):
    """Round to 4 decimals, half up, as JavaScript Math.round does it."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value == int(value) else value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hours_since(release, moment):
    """Hours from release, floored so pre-release reads stay usable in logs."""
    return max(0.25, (moment - release).total_seconds() / 3600.0)


def ols_slope(xs, ys):
    """Least-squares slope of ys on xs; None when the xs do not vary."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def family_exponent(description):
    """Earn-growth exponent prior from the trophy's own description text."""
    text = (description or "").lower()
    if "chapter" in text or "final mission" in text:
        return EXPONENT_STORY
    if re.search(r"\b(250|100|50|30|20)\b", text):
        return EXPONENT_GRIND
    if any(word in text for word in ("every", "all of", "100%", "sets", "strands")):
        return EXPONENT_GRIND
    return EXPONENT_ONEOFF


def read_rates(read, n_trophies):
    """Rates of one read as floats, None where the read lacked the trophy."""
    out = []
    rates = read.get("rates") or []
    for i in range(n_trophies):
        value = rates[i] if i < len(rates) else None
        out.append(float(value) if value is not None else None)
    return out


def denominator_forecast(reads, release, target_time, last_players):
    """Forecast tracked players at the target: logistic in log-hours."""
    points = []
    for read in reads:
        players = read.get("players_tracked")
        if players and players > 0:
            moment = parse_time(read.get("slot") or read["at"])
            points.append((hours_since(release, moment), float(players)))
    if not points:
        return float(last_players)
    last_t = points[-1][0]
    target_t = hours_since(release, target_time)
    slope = None
    if len({p for _, p in points}) >= 2:
        slope = ols_slope([math.log(t) for t, _ in points],
                          [math.log(p) for _, p in points])
    if slope is None:
        slope = SLOPE_PRIOR
    slope = min(4.0, max(0.0, slope))
    # Logistic P(t) = A / (1 + C * t^-b), with C pinned to the last point.
    c_const = (ASYMPTOTE_PLAYERS / max(1.0, last_players) - 1.0) * (last_t ** slope)
    pred = ASYMPTOTE_PLAYERS / (1.0 + c_const * (target_t ** (-slope)))
    # Players tracked never shrink, and never exceed the asymptote.
    return min(ASYMPTOTE_PLAYERS, max(float(last_players), pred))


def numerator_forecast(reads, release, target_time, idx, last_earns, exponent):
    """Forecast one trophy's earn count at the target: power law in hours."""
    target_t = hours_since(release, target_time)
    xs, ys = [], []
    for read in reads:
        rates = read_rates(read, idx + 1)
        rate = rates[idx]
        players = read.get("players_tracked")
        if rate is None or not players:
            continue
        moment = parse_time(read.get("slot") or read["at"])
        earns = rate / 100.0 * players
        if earns > 0:
            xs.append(math.log(hours_since(release, moment)))
            ys.append(math.log(earns))
    fitted = None
    if len(xs) >= 2 and len(set(ys)) >= 2:
        fitted = ols_slope(xs, ys)
    if fitted is None:
        fitted = exponent
    fitted = min(1.5, max(0.05, fitted))
    last_t = hours_since(release, parse_time(reads[-1].get("slot") or reads[-1]["at"]))
    pred = last_earns * ((target_t / last_t) ** fitted)
    # Earn counts never fall.
    return max(float(last_earns), pred)


def structural_rates(case, reads, target_time):
    """Structural (ratio-model) rates and persistence rates at target_time."""
    trophies = case["trophies"]
    n = len(trophies)
    release = parse_time(case["game"]["release_date"] + "T00:00:00Z")
    last = reads[-1]
    last_players = last.get("players_tracked") or 1
    last_rates = read_rates(last, n)
    players_target = denominator_forecast(reads, release, target_time, last_players)
    structural = []
    persistence = []
    for i, trophy in enumerate(trophies):
        last_rate = last_rates[i]
        if last_rate is None:
            last_rate = 1.0
        persistence.append(last_rate)
        earns_last = last_rate / 100.0 * last_players
        exponent = family_exponent(trophy.get("description", ""))
        earns_target = numerator_forecast(reads, release, target_time, i,
                                          earns_last, exponent)
        structural.append(100.0 * earns_target / players_target)
    return structural, persistence


def choose_shrink(case, reads):
    """Pick the persistence shrink weight by one-step-ahead backtest on the
    case's own history; the default when no step shows a real move."""
    trophies = case["trophies"]
    n = len(trophies)
    # Trophy #2's artifact rate must not steer the weight.
    usable = [i for i, t in enumerate(trophies) if t["id"] != 2]
    candidates = [0.0, 0.2, 0.35, 0.5, 0.65]
    totals = {w: 0.0 for w in candidates}
    steps = 0
    for k in range(1, len(reads)):
        prefix, truth = reads[:k], reads[k]
        if not prefix:
            continue
        truth_rates = read_rates(truth, n)
        if all(v is None for v in truth_rates):
            continue
        # Only steps where something actually moved carry information.
        prev_rates = read_rates(prefix[-1], n)
        moved = any(
            a is not None and b is not None and abs(a - b) > 1e-9
            for a, b in zip(prev_rates, truth_rates)
        )
        if not moved:
            continue
        target_time = parse_time(truth.get("slot") or truth["at"])
        try:
            struct, persist = structural_rates(case, prefix, target_time)
        except Exception:
            continue
        steps += 1
        for w in candidates:
            for i in usable:
                y = truth_rates[i]
                if y is None:
                    continue
                blended = inv_logit((1.0 - w) * logit(struct[i]) + w * logit(persist[i]))
                totals[w] += abs(logit(y) - logit(blended))
    if steps == 0:
        return SHRINK_DEFAULT
    best = min(candidates, key=lambda w: (totals[w], abs(w - SHRINK_DEFAULT)))
    return best


def fishing_family_median(case, medians):
    """Median for trophy #2 from its activity family (other trophies whose
    description mentions fishing); None when the family is absent."""
    family = []
    for trophy, median in zip(case["trophies"], medians):
        if trophy["id"] == 2:
            continue
        if "fish" in (trophy.get("description", "") or "").lower():
            family.append(median)
    if not family:
        return None
    family.sort()
    return family[len(family) // 2]


def forecast_case(case, name):
    if case.get("levels", LEVELS) != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    trophies = case["trophies"]
    reads = case.get("history") or []
    target_time = parse_time(case["target"])
    days = case["horizon_minutes"] / 1440.0

    if not reads:
        # No history at all: flat low medians with a very wide spread.
        medians = [1.0 for _ in trophies]
        sigmas = [2.0 for _ in trophies]
    else:
        structural, persistence = structural_rates(case, reads, target_time)
        shrink = choose_shrink(case, reads)
        medians = []
        for s, p in zip(structural, persistence):
            blended = inv_logit((1.0 - shrink) * logit(s) + shrink * logit(p))
            medians.append(clamp_pct(blended))
        # Trophy #2: never trust its artifact rate; take the fishing family.
        for i, trophy in enumerate(trophies):
            if trophy["id"] == 2:
                family_median = fishing_family_median(case, medians)
                medians[i] = clamp_pct(family_median if family_median is not None else 1.5)
        # Spread: random-walk floor plus at least one refresh of jump risk.
        base = math.sqrt((RW_SIGMA * math.sqrt(days)) ** 2
                         + (JUMP_SIGMA * math.sqrt(1.0 + days)) ** 2)
        sigmas = []
        for i, trophy in enumerate(trophies):
            sigma = base * (1.5 if trophy["id"] == 2 else 1.0)
            sigmas.append(sigma)

    rows = []
    for trophy, median, sigma in zip(trophies, medians, sigmas):
        center = sigma
        tail = sigma * TAIL_WIDEN
        spreads = [tail, center, 0.0, center, tail]
        lg = logit(median)
        quantiles = []
        prev = 0.01
        for z, spread in zip(Z, spreads):
            q = round4(clamp_pct(inv_logit(lg + z * spread)))
            q = max(q, prev)
            quantiles.append(q)
            prev = q
        rows.append({"id": trophy["id"], "q": quantiles})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        # Validate the output shape before writing: one row per trophy, five
        # finite numbers 0..100, non-decreasing, or the case scores as if
        # every quantile were the last-read rate and takes no prize.
        assert len(forecast["trophies"]) == len(case["trophies"])
        for row in forecast["trophies"]:
            assert len(row["q"]) == 5
            assert all(isinstance(v, (int, float)) and math.isfinite(v)
                       and 0 <= v <= 100 for v in row["q"])
            assert all(row["q"][i] <= row["q"][i + 1] for i in range(4))
        out = json.dumps(forecast, separators=(",", ":")) + "\n"
        assert len(out.encode("utf-8")) <= 65536
        (OUTPUT_DIR / f"{path.stem}.out").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
