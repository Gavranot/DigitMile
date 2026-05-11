import { check } from "k6";
import http from "k6/http";

import {
  baseUrl,
  benchmarkHeaders,
  buildUnityPayload,
  envInt,
  fetchApiCsrf,
  loadDatasetReport,
  loadScenarioConfig,
  randomChoice,
} from "./common.js";


// Lesson-bell burst — the second of two regimes from
// docs/research/ingest-capacity-model.md §5.  Unlike the steady scenarios,
// the load shape here matters more than the peak rate: 30 students per
// classroom finish their last Run within ~60s of the bell, multiple
// classrooms align, and the ingest endpoint sees a short transient where
// the Redis write buffer absorbs the spike on behalf of PostgreSQL.
//
// Stage profile (configurable per scenario JSON):
//   bell_ramp_seconds   (default 10)  ramp 0 → target_rate
//   bell_hold_seconds   (default 60)  hold target_rate
//   bell_drain_seconds  (default 30)  drain target_rate → 0
//
// Peak rate comes from traffic.ingest_rate_per_sec.  VU sizing follows the
// existing convention: pre-allocate generously so drops come from server
// slowness, not VU starvation.
const datasetReport = loadDatasetReport();
const scenarioConfig = loadScenarioConfig();
const trafficConfig = scenarioConfig.traffic || {};
const expectedMode = __ENV.INGEST_EXPECTED_MODE || trafficConfig.ingest_expected_mode || "accepted";

const peakRate = envInt("INGEST_RATE_PER_SEC", trafficConfig.ingest_rate_per_sec || 30);
const rampSeconds = envInt("BELL_RAMP_SECONDS", trafficConfig.bell_ramp_seconds || 10);
const holdSeconds = envInt("BELL_HOLD_SECONDS", trafficConfig.bell_hold_seconds || 60);
const drainSeconds = envInt("BELL_DRAIN_SECONDS", trafficConfig.bell_drain_seconds || 30);

const preAllocatedVUs = envInt(
  "INGEST_PRE_ALLOCATED_VUS",
  trafficConfig.ingest_pre_allocated_vus || Math.max(20, peakRate * 2)
);
const maxVUs = envInt(
  "INGEST_MAX_VUS",
  trafficConfig.ingest_max_vus || Math.max(preAllocatedVUs * 2, peakRate * 4)
);


export const options = {
  scenarios: {
    lesson_bell: {
      executor: "ramping-arrival-rate",
      startRate: 0,
      timeUnit: "1s",
      preAllocatedVUs,
      maxVUs,
      stages: [
        { duration: `${rampSeconds}s`, target: peakRate },
        { duration: `${holdSeconds}s`, target: peakRate },
        { duration: `${drainSeconds}s`, target: 0 },
      ],
      tags: { traffic_class: "ingest", endpoint_group: "runs_ingest" },
    },
  },
  thresholds: {
    // Bell-burst tolerances are deliberately loose. The thesis question is
    // "does the Redis-buffered ingest absorb the spike without 5xx?", not
    // "is p95 low under saturation". Tighten these if you want a hard pass.
    "http_req_failed": ["rate<0.02"],
  },
};


export function setup() {
  return { csrf: fetchApiCsrf() };
}


export default function (setupData) {
  const targets = datasetReport.ingest_targets_hot_week || datasetReport.ingest_targets || [];
  if (targets.length === 0) {
    throw new Error("No ingest targets found in DATASET_REPORT");
  }

  const response = http.post(
    `${baseUrl()}/panel/api/runs/ingest/`,
    JSON.stringify(buildUnityPayload(randomChoice(targets), datasetReport)),
    {
      headers: benchmarkHeaders(datasetReport, {
        "Content-Type": "application/json",
        "X-CSRFToken": setupData.csrf.csrfToken,
        Cookie: setupData.csrf.cookieHeader,
      }),
      tags: {
        traffic_class: "ingest",
        endpoint_group: "runs_ingest",
        expected_mode: expectedMode,
      },
    }
  );

  if (expectedMode === "rejected") {
    check(response, {
      "lesson-bell closed-week ingest rejected": (value) => value.status === 409,
    });
    return;
  }

  check(response, {
    "lesson-bell ingest accepted": (value) => [200, 201, 202].includes(value.status),
  });
}
