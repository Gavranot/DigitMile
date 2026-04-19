# Documentation Consolidation — Final Report

**Branch:** `feat/optimizations`
**Date:** 2026-04-19

This report summarizes the doc-consolidation work carried out in five phases. See `docs-audit.md` for the Phase 1–2 inventory and evidence trail. Commits: `3d349e3` (Phase 1), `fa6844b` (Phase 2), Phase 3 commit (consolidation), `27bcced` (Phase 4 AGENTS.md).

---

## 1. Summary of changes

| Outcome | Count | Where |
|---------|------:|-------|
| Docs moved + kept | 23 | `docs/` (16 renames preserved history via `git mv`; 3 untracked files moved via `mv`; 4 moves across merge touch-ups) |
| Docs deleted as STALE | 14 | 12 × `docs/old/*`, `DigitMilePanel/docs/PRODUCTION_DEPLOYMENT.md`, `DigitMilePanel/docs/VISUALIZATIONS_AND_STATISTICS.MD` |
| Intermediate docs deleted after salvage | 2 | `docs/decisions/production-deployment-notes.md` (prefix table was already in `data-model.md`), `docs/decisions/old-docs-index.md` (internal `docs/new/` index, superseded by new `docs/README.md`) |
| Docs merged | 2 | `docs/old/LANGUAGE_SWITCHER_SETUP.md` + `docs/old/TRANSLATION_GUIDE.md` → `docs/guides/i18n.md` |
| Docs rewritten in place | 2 | Root `README.md` (trimmed to overview), `docs/decisions/write-buffering-adr.md` (plan → past-tense ADR) |
| Docs with surgical content updates | 5 | `docs/reference/analytics-and-dashboard.md`, `docs/decisions/optimality-metrics-proposal.md`, `docs/decisions/ingest-optimization-plan.md`, `docs/decisions/hot-week-load-testing-plan.md`, `docs/decisions/hot-week-load-testing-checklist.md` |
| New docs written from the code | 8 | `docs/README.md`, `docs/getting-started.md`, `docs/reference/configuration.md`, `docs/reference/management-commands.md`, `docs/guides/deployment.md`, `docs/guides/ci-cd.md`, `docs/guides/testing.md`, `docs/guides/load-testing.md` |
| `AGENTS.md` edits | 9 surgical | path refs updated, cache timeout corrected, k8s downgraded to scaffolding, `docs/new/`/`docs/old/` language removed |

**Total file deletions in Phase 3:** 16. **Total new files:** 9 (8 new docs + the merged i18n guide file created via overwrite of the moved file). **Total moves via `git mv`:** 19 (history preserved).

Resulting folder layout:

```
docs/
├── README.md
├── architecture.md
├── getting-started.md
├── reference/
│   ├── analytics-and-dashboard.md
│   ├── configuration.md
│   ├── dashboard-metrics.md
│   ├── data-model.md
│   ├── glossary.md
│   ├── ingestion-api.md
│   ├── management-commands.md
│   ├── registration-and-admin.md
│   ├── rollup-schema.md
│   └── run-analytics-models.md
├── guides/
│   ├── ci-cd.md
│   ├── deployment.md
│   ├── i18n.md
│   ├── load-testing.md
│   ├── operations.md
│   ├── rollup-runbook.md
│   ├── ssl.md
│   └── testing.md
├── decisions/
│   ├── dashboard-tasks.md
│   ├── dashboard-visualization-rework.md
│   ├── hardware-sizing.md
│   ├── hot-week-load-testing-checklist.md
│   ├── hot-week-load-testing-plan.md
│   ├── ingest-optimization-plan.md
│   ├── next-phase-log.md
│   ├── optimality-metrics-proposal.md
│   ├── weekly-rollup-prd.md
│   └── write-buffering-adr.md
└── research/
    ├── north-macedonia-weekly-load-estimate.md
    └── voved.md
```

Empty folders removed: `docs/old/`, `docs/new/`, `DigitMilePanel/docs/`.
Files kept in original locations (by design): `README.md` and `AGENTS.md` at repo root; `benchmarks/README.md` co-located with its framework.

---

## 2. `<!-- TODO: verify -->` markers left behind

**None.** Every claim I kept in the consolidated docs was verified against the code. When a claim could not be verified with confidence — for example, the five optimizations in `ingest-optimization-plan.md` or the three proposals in `optimality-metrics-proposal.md` — I prefixed the document with an explicit "NOT YET APPLIED" or "PROPOSED" header rather than leaving an uncertain passage in place.

---

## 3. MISSING features that were documented from scratch

Phase 2 §2.c identified seven gaps. Coverage delivered in Phase 3:

| Gap | Coverage | Derived from |
|-----|----------|--------------|
| 7-day dashboard query cache + invalidation semantics | `docs/reference/analytics-and-dashboard.md` §Caching and `AGENTS.md` §11 dashboard loading model | `views.py:2137-2152` (`cache.set(... timeout=604800)`); `management/commands/compact_weekly_runs.py:224`, `rebuild_weekly_rollups.py:70` (`cache.delete_pattern("teacher_stats_viz:*")`) |
| Explicit `flusher` service | `docs/getting-started.md` §3, `docs/reference/management-commands.md` §flush_ingest_buffer, `docs/decisions/write-buffering-adr.md` (ADR), `AGENTS.md` §21 | `docker-compose.yml:104-124` (`flusher` service); `digitmileapi/management/commands/flush_ingest_buffer.py`; `digitmileapi/ingest_router.py:161` (LPUSH) |
| Consolidated management-commands reference | `docs/reference/management-commands.md` (all 13 commands with flags) | `DigitMilePanel/digitmileapi/management/commands/` (file listing) + each command's `add_arguments` |
| CI/CD current reality | `docs/guides/ci-cd.md` | `.github/workflows/{build,deploy,deploy-to-environment,django,game}.yml` |
| Getting-started path | `docs/getting-started.md` | `docker-compose.yml`, `Dockerfile.compose`, `DigitMilePanel/manage.py`, `scripts/quick-start.sh` |
| Test execution | `docs/guides/testing.md` | `DigitMilePanel/digitmileapi/tests.py`, `DigitMilePanel/digitmileapi/test_rollup_accuracy.py`, `.github/workflows/django.yml` |
| Benchmark env-var wiring | `docs/reference/configuration.md` §Benchmark-only, `docs/guides/load-testing.md` | `benchmarks/run_scenario.py`, `benchmarks/docker-compose.benchmark.yml`, `digitmile/settings.py:248` (`BENCHMARK_TIME_OVERRIDE_ENABLED`) |

Each new doc was written from the code only; no rationale was invented.

---

## 4. Contradictions resolved

| Contradiction | Resolution |
|---------------|------------|
| `docs/new/backend-analytics-and-dashboard.md` claimed the dashboard cache was 300 s; actual code is `timeout=604800` (7 days). | Rewrote the §Caching block in `docs/reference/analytics-and-dashboard.md` and the matching bullet in `AGENTS.md` §11 dashboard loading model. |
| Root `README.md` linked to `./CI-CD-SETUP.md`, `./DEPLOYMENT.md`, `./SSL-SETUP.md` at repo root — none existed there (they lived in `docs/old/`, now deleted). | Rewrote root `README.md` as a short overview that links into `docs/`. |
| `docs/new/write-buffering-implementation.md` was a future-tense "files to change" plan, but the Redis write-buffering, `flusher` service, and `flush_ingest_buffer` command are all in the code. | Rewrote as `docs/decisions/write-buffering-adr.md` in past tense as an Accepted/Implemented ADR. |
| Hot-week load-testing plan said "dataset generation anchors weeks to real `timezone.now()`" — but `prepare_benchmark_dataset.py` has `--anchor-week-start` and Slice 1 Milestones A–F1 have all landed. | Added a "Status as of 2026-04-19" note at the top of both `docs/decisions/hot-week-load-testing-plan.md` and the checklist, clarifying what has shipped and what remains (Slices 2 and 3). |
| `OPTIMALITY_METRICS.md` read like specification for existing metrics, but no `move_optimality.py` / `StudentWeekOptimalityStats` / `dominated_rate` exists. | Added a "Status: PROPOSED — not implemented" header at the top of `docs/decisions/optimality-metrics-proposal.md`. |
| `ingest-performance-optimizations.md` described five optimizations, but all five still-referenced fields (`offered_cards`, `bot_positions_before/after`, `chosen_card`, `game_map`) remain in `models.py:470–543`. | Added a "Status: NOT YET APPLIED" header that also clarifies the separate Redis write-buffering optimization **has** shipped. |
| `docs/new/` vs `docs/old/` as trust order in `AGENTS.md`. | Rewrote AGENTS §2 to reference the consolidated `docs/` folder with `docs/README.md` as the entry point. |
| `k8s/` described in `AGENTS.md` as "less authoritative than Docker Compose" — in reality not wired to any deploy path at all. | Demoted explicitly in `AGENTS.md` §1 and §3 to "outdated scaffolding, not a live deploy path". Removed detailed k8s file listings. |
| `DigitMilePanel/docs/VISUALIZATIONS_AND_STATISTICS.MD` (discovered during consolidation — not in the Phase 1 inventory) described the legacy `RunStatistics` dashboard path; same content also lived in `docs/reference/dashboard-metrics.md` and `docs/reference/analytics-and-dashboard.md`. | Deleted — explicit self-description at the top of the file already flagged it as legacy. |

---

## 5. `AGENTS.md` changes

Surgical edits only; structure, section numbers, and tone preserved. Specific lines changed:

1. §1 `k8s/` description → "outdated scaffolding, not a live deploy path".
2. §2 trust order — removed `docs/new/` and `docs/old/`; now points at `docs/README.md` and notes that the root `README.md` is a short pointer.
3. §2 known-drift list rewritten — old README staleness and `docs/old/` purgatory no longer apply; what remains is the pending-work state of two decision docs.
4. §3 top-level map — replaced `docs/new/` and `docs/old/` bullets with one `docs/` bullet including the subfolder structure. Condensed the three `k8s/` file bullets into one scaffolding disclaimer.
5. §11 dashboard loading model — cache timeout corrected from 5 minutes to 7 days, cache backend explicitly named, invalidation semantics added.
6. §11 learning-curves section — reference changed from `docs/new/` to `docs/decisions/weekly-rollup-prd.md`.
7. §21 docs-updates rule — reference changed from `docs/new/` to `docs/` with subfolder guidance.
8. §22 known sharp edges — removed now-fixed items (README pointing to missing files, outdated claim about tests), retained the two real drifts (`.env.example`'s `SECRET_KEY` naming and dead code in `django.yml`), and sharpened the k8s call-out.
9. §23 recommended reading paths — rewrote every path from `docs/new/<old-name>.md` to its new location under `docs/{architecture,reference,guides}/...`.

**No restructuring of `AGENTS.md` was performed**, per the Phase 4 directive. Sections 4–20 and 24 were untouched.

---

## 6. Verifications done before the consolidation

The per-doc categorizations in `docs-audit.md` §2.b were backed by direct code reads:

- All 13 management commands listed in `digitmileapi/management/commands/` against the claims in every doc that named one.
- All six services in `docker-compose.yml` against README / deployment docs.
- The complete env-var set in `settings.py` against the `docs/reference/configuration.md` / former `ENV-FILE-EXPLAINED.md` inventory.
- All routes in `digitmile/urls.py` + `digitmileapi/urls.py` + `ingest_router.py` against ingestion / admin / registration docs.
- Model-field existence (e.g. `offered_cards`, `game_map`, `move_optimality.py`, `StudentWeekOptimalityStats`) via Grep before labelling any doc STALE vs pending-work.

---

## 7. What I did not change (intentional)

- `benchmarks/README.md` — left in place as the framework's co-located source of truth; `docs/guides/load-testing.md` is a short pointer into it.
- `docs/decisions/next-phase-log.md` line 744 — contains the string `"docs/new/"` inside a historical directive. This is a record of what was originally instructed, not a live link, so I left it.
- `k8s/` contents — untouched per user guidance (it is scaffolding; only its framing in docs was clarified).
- The Unity WebGL game build under `DigitMile/game/` — the task was documentation-only, and the guardrails explicitly forbade source-code changes.
- `.github/workflows/*.yml` — noted the dead `build-and-push` job and missing test invocation in `django.yml` as observations in `docs/guides/ci-cd.md` §"Known gotchas" and `AGENTS.md` §22, but did not modify the workflow files.

---

## 8. Open items worth noting

- `django.yml` CI does not run the test suite. Adding `python manage.py test digitmileapi` to that workflow would be a small, separate change.
- `DigitMilePanel/.env` is legacy — some older tooling paths may still read it. The compose stack reads the root `.env` via `env_file:`. A future cleanup could remove `DigitMilePanel/.env`'s relevance entirely.
- `docs/decisions/dashboard-tasks.md` and `docs/decisions/dashboard-visualization-rework.md` are preserved historical roadmaps; if these are no longer the plan-of-record, someone with product context should either update or supersede them.
- The four open questions in `docs-audit.md` §2.f were answered by the user (move VOVED to research, absorb DigitMilePanel docs into `docs/`, preserve task-lists, keep `docs/research/`). All are applied.
