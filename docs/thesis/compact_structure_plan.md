# Thesis Structure Plan

Target: at least 30 pages. Since the faculty rule is a minimum, the thesis should not be compressed to the edge of 30 pages. It should still avoid generic filler, but it needs enough technical detail to show the actual engineering work: telemetry modeling, weekly analytics formulas, compaction/archive design, optimizations, and load-testing validation.

## Recommended Page Budget

| Part | Target pages | Notes |
| ---- | ------------ | ----- |
| Abstract + contents | 1.0-1.5 | Dense overview, not a substitute for technical chapters. |
| 1. Introduction | 3.0-4.0 | Motivation, problem, goals, contribution. Avoid generic digitalization filler. |
| 2. Requirements and system design | 6.0-7.0 | Include the load-model math that derives benchmark RPS values. |
| 3. Implementation | 6.0-8.0 | Use the fuller implementation draft, but keep field details in tables. |
| 4. Analytics and weekly aggregation logic | 7.0-9.0 | Main technical core: formulas, counters, dimensions, dashboard mapping. |
| 5. Optimization and load-testing validation | 8.0-10.0 | Main empirical core: scenarios, before/after comparisons, NFR results. |
| 6. Conclusion | 1.5-2.0 | Contributions, limitations, future work. |
| Bibliography | 1.0-2.0 | Keep references relevant. |

Total: about 33-43 pages depending on figures/tables. This is appropriate for a 30-page minimum.

## Current Assessment

The current thesis is not too detailed. It is currently lacking the most important technical evidence because the main draft mostly contains introduction, requirements, and architecture. The work spent on optimization and compaction should become a central part of the thesis, not a side note.

The missing high-value material is:

- the mathematical model used to derive benchmark load values;
- the formulas behind the weekly aggregate tables;
- the mapping from telemetry fields to pedagogical metrics;
- the concrete implementation of Redis buffering, Flusher, rollups, replay archives, and compaction;
- the optimization narrative: baseline problem, change made, measured result;
- the k6 scenario results and how they validate each NFR.

## High-Signal Thesis Argument

Use this chain repeatedly:

```text
requirement -> architectural pressure -> implementation mechanism -> validation evidence
```

Example:

```text
NFR: 11 RPS sustained ingest on limited VPS
Pressure: synchronous PostgreSQL writes make request latency depend on DB transaction cost
Mechanism: Pydantic validation + Redis list + flusher bulk_create
Evidence: k6 ingest/endurance scenarios, p95 latency, error rate, Redis drain time
```

## Suggested Final Outline

```text
1. Вовед
1.1 Контекст и мотивација
1.2 Формулирање на проблемот
1.3 Цели и придонеси
1.4 Структура

2. Барања и системски дизајн
2.1 Постоечка Unity игра и телеметриски потреби
2.2 Функционални барања
2.3 Модел на оптоварување и изведување на benchmark RPS
2.4 Нефункционални барања
2.5 Архитектура на високо ниво
2.6 Клучни архитектонски одлуки

3. Имплементација на платформата
3.1 Backend routing and ingest endpoint
3.2 Telemetry schema and validation
3.3 Redis buffer and Flusher persistence
3.4 Raw telemetry data model
3.5 Weekly aggregate and archive data model
3.6 Teacher dashboard read path
3.7 Docker deployment topology

4. Аналитички модел и неделна агрегација
4.1 Педагошки мапирања на картички и потези
4.2 Основни метрики: точност, победа, време, резултат
4.3 Метрики по ниво, картичка, услов и број
4.4 Формули за неделни rollup табели
4.5 Replay archive and historical consistency

5. Оптимизација и валидација
5.1 Benchmark methodology and target hardware
5.2 Load-model math mapped to k6 scenarios
5.3 Baseline synchronous ingest vs Redis write buffer
5.4 PgBouncer experiment and removal
5.5 Query/cache optimization for dashboard
5.6 National-medium/high and lesson-bell scenarios
5.7 Overload recovery and weekly compaction validation
5.8 Discussion of limits

6. Заклучок
```

## Chapter 4 Formula Strategy

Chapter 4 should contain enough math to make the analytics defensible. Use one formula block per metric family:

- run-level rates: accuracy, win rate, average score, average time;
- level-level metrics: same rates grouped by level;
- card metrics: exposure, adoption, correctness, decision time;
- conditional metrics: tile/bag condition correctness;
- special tile metrics: trigger rate and chain length distribution;
- number-choice metrics: choice distribution and decision time;
- learning trend: bucketed moving trend over fixed-size run buckets.

Then map formula families to aggregate tables in a compact table.

## Chapter 5 Validation Strategy

Use a table for all benchmark scenarios, then discuss the important deltas in prose:

- synchronous ingest baseline vs Redis write buffer + Flusher;
- PgBouncer on/off result;
- cache off/on for dashboard queries;
- sustained national load;
- lesson-bell burst;
- overload recovery;
- storage/year simulation or compaction validation.

The strongest validation narrative is not “the system is scalable” in the abstract. It is:

```text
The implemented optimizations satisfy the thesis NFRs on the target VPS class while preserving replay and weekly analytics correctness.
```
