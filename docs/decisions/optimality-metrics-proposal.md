# Move-Optimality Metrics — Design Proposal

> **Status: PROPOSED — not implemented.** None of the three approaches below exist in code yet. No `move_optimality.py` module, no `StudentWeekOptimalityStats` table, no `dominated_rate` / `regret` / `ev_regret` fields on any model. This document is a design proposal captured so the thinking isn't lost; it requires a design review before implementation.

A proposal for measuring the *quality* of student card choices in DigitMile,
beyond the existing binary `was_correct` flag. All three approaches use data
that is already captured per turn (`TurnEvent.offered_cards`, `chosen_card`,
`tile_before_index`, `tile_before_type`, `place_before`, `bot_positions_before`,
plus `Run.game_map` and the per-level deck JSON loaded by
`analytics.py:load_level_deck`).

---

## Why this is worth adding

The current accuracy signal (`was_correct` per turn, `correct_moves` /
`wrong_moves` per run) is binary and game-determined: it tells you whether a
move "worked" but not whether it was the *best* move available. Two students
with identical accuracy can be playing very differently — one consistently
picking near-optimal cards, another scraping by on lucky offers. An optimality
metric separates *judgment* from *outcome*.

---

## 1. Dominated-choice rate (cheapest, most defensible)

**Idea.** For each turn, check whether any card in `offered_cards` *strictly
dominates* the chosen card — i.e. produces an equal-or-better outcome on every
dimension (distance gained, place after, side-effect risk) with no downside.
Picking a dominated card is unambiguously a mistake.

**Formula.**
```
dominated_rate(student) = (turns where ∃ dominator in offered_cards) / total_turns
```

**Why start here.** It needs no objective-function debate: dominance is a
partial order, not a ranking. If card A is at least as good as card B on every
axis and strictly better on one, B is wrong to pick. End of story. Defensible
even to a sceptical reviewer.

**Implementation cost.** Low. For each offered card, parse it (`parse_card`),
simulate its deterministic effect from `tile_before_index` using `game_map`,
collect resulting `(tile_after, place_after, side_effect_severity)`. Then run
pairwise dominance checks within the offered set. ~O(k²) per turn where k is
typically 3–5.

**Caveats.** Most turns will have *no* dominated alternative — the offered
cards usually span genuinely different trade-offs. So this metric tends toward
zero, and only flags egregious mistakes. That's a feature, not a bug: a high
dominated-choice rate is a strong red flag.

---

## 2. Per-turn regret (continuous quality signal)

**Idea.** Pick a numeric objective (e.g. *distance advanced*, *expected
place-after*, *expected score gain*). For each turn, compute the value of every
offered card under a deterministic forward simulation. Define:

```
regret(turn) = value(best_offered_card) − value(chosen_card)
```

Average regret per (student, level, family) gives a continuous "how far from
optimal" signal that the binary `was_correct` flag cannot.

**Aggregations worth surfacing.**
- `avg_regret(student)` — overall judgment quality.
- `avg_regret_by_family(student, family)` — *which concept* the student handles
  poorly. A student could be near-optimal on `move` cards but high-regret on
  `conditional_tile`, indicating they pick the conditional but do not reason
  about which branch will fire.
- `regret_trend_over_buckets` — fed into the existing 5-run bucket pipeline,
  this becomes a learning curve for *judgment* rather than just for accuracy.

**Implementation cost.** Medium. Requires a deterministic per-card simulator
that resolves special-tile chains (the data already records the actual chain
in `SpecialTileTrigger`, but for *unchosen* cards we have to simulate). The
simulator is also useful for replay rendering, so it pays for itself.

**Caveats.**
- "Optimal" depends on the objective. Distance, place, and score do not always
  agree. Pick one defensible objective per metric and label it explicitly.
- Bot moves are stochastic. For a deterministic regret value, freeze bot
  positions at `bot_positions_before` and ignore their next moves; the regret
  is then "regret given the current snapshot," which is what a student
  reasoning at the moment of choice would consider.

---

## 3. Bag-aware expected value (richest, hardest)

**Idea.** The conditional-bag cards (`IfBagEqualX…`, `IfBagLess…`,
`IfBagGreater…`) and the `BagCount`/`ForXMoveY` cards reward students who
*reason about uncertainty* — what numbers are still in the bag, what tile types
remain, what the opponent might draw. Using `load_level_deck` plus the running
record of cards already played in the run, you can compute the posterior
distribution over the next bag draw, and from it the *expected value* of each
offered card.

**Formula sketch.**
```
EV(card | history) = Σ_outcome P(outcome | remaining_bag) × value(outcome)
ev_regret(turn)     = EV(best_offered | history) − EV(chosen | history)
```

**Why it matters pedagogically.** Conditional-bag cards literally model
`if (random_variable < threshold) then A else B`. The optimal play is *not* the
play that ends up working; it is the play with the highest expected value
*given what was knowable at the time*. That distinction — outcome vs decision
quality — is the same distinction professional programmers draw between "the
code worked" and "the code is correct under all inputs."

**Implementation cost.** High. Needs:
- Run-state tracking of the bag draws so far (the data is in `TurnEvent`
  ordering, derivable from `chosen_number` history per the existing
  `_iter_turns_with_bag_number` helper in `analytics.py`).
- A small Monte Carlo (or, given small bag sizes, an analytic enumeration) over
  remaining bag states to compute EV for each offered card.
- A defensible value function — same problem as approach #2, but now over
  distributions.

**Caveats.** Computationally heavier; harder to explain to teachers (they will
ask "why did you say card A is optimal when card B actually worked?"). Best
introduced after #1 and #2 have established the vocabulary.

---

## Recommended rollout

1. **Ship #1 first.** Dominated-choice rate per student/level. One column on
   the existing teacher dashboard. Low risk, defensible, immediately useful.
2. **Add #2 once the simulator exists.** Per-family regret as a heatmap —
   teachers can see at a glance which concept each student is sloppy on.
3. **Treat #3 as research.** Worth a thesis chapter; possibly worth shipping
   to teachers later, but requires careful UX so they read it as "decision
   quality under uncertainty," not as "the system says they were wrong."

---

## Where this would live in the codebase

- A new module `digitmileapi/move_optimality.py` for the per-turn simulator and
  the three metric calculations.
- New rollup tables (e.g. `StudentWeekOptimalityStats`) extending the existing
  `StudentWeekBase` pattern, populated inside the existing
  `weekly_aggregation.py` loop where `TurnEvent`s are already iterated.
- New rollup-side aggregations in `rollup_analytics.py` mirroring the existing
  pattern (sum / count / sum_sq for streaming-variance reconstruction of
  regret stddev).

---

## Relationship to existing metrics

- **Complements `was_correct`**, does not replace it. `was_correct` is a
  game-rule judgment; optimality is a counterfactual judgment.
- **Sharpens `card_accuracy_by_family_by_level`.** A student with 80% accuracy
  on conditional cards but high regret on the same family is *picking the right
  card type for the wrong reason* — they get conditionals right when offered
  them, but often there was a strictly better non-conditional card available.
- **Feeds the learning-curve pipeline.** Average regret per 5-run bucket is a
  drop-in replacement for accuracy in the existing
  `StudentRunBucketTrend`-style trend visualisations.
