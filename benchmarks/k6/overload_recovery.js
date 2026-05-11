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


// Overload-recovery scenario — closes NFR-5 from
// docs/decisions/thesis-benchmark-plan.md §3.
//
// The system is deliberately driven into overload (2x the steady-state
// capacity target) for a sustained window, then load drops to the NFR-1
// baseline rate.  The thesis question is: once the load drops, how long
// does the system take to return to NFR-1 p95?
//
// Four-stage profile, all knobs configurable per scenario JSON:
//   overload_ramp_seconds      (default 120) ramp 0 -> peak_rate
//   overload_hold_seconds      (default 300) hold at peak_rate (the overload)
//   overload_drop_seconds      (default 1)   snap drop peak_rate -> recovery_rate
//   overload_recovery_seconds  (default 300) hold at recovery_rate (NFR-1 baseline)
//
// The drop stage is deliberately short (1 s) to model a real-world burst
// ending abruptly rather than tapering.  The recovery hold is where the
// p95-recovery-time NFR is evaluated; in post-processing, walk the
// http_req_duration time series and find the first point in the recovery
// window where p95 falls back below the NFR-1 threshold (1000 ms).
const datasetReport = loadDatasetReport();
const scenarioConfig = loadScenarioConfig();
const trafficConfig = scenarioConfig.traffic || {};
const expectedMode = __ENV.INGEST_EXPECTED_MODE || trafficConfig.ingest_expected_mode || "accepted";

const peakRate = envInt("INGEST_RATE_PER_SEC", trafficConfig.ingest_rate_per_sec || 22);
const recoveryRate = envInt(
  "OVERLOAD_RECOVERY_RATE",
  trafficConfig.overload_recovery_rate || 11
);
const rampSeconds = envInt(
  "OVERLOAD_RAMP_SECONDS",
  trafficConfig.overload_ramp_seconds || 120
);
const holdSeconds = envInt(
  "OVERLOAD_HOLD_SECONDS",
  trafficConfig.overload_hold_seconds || 300
);
const dropSeconds = envInt(
  "OVERLOAD_DROP_SECONDS",
  trafficConfig.overload_drop_seconds || 1
);
const recoverySeconds = envInt(
  "OVERLOAD_RECOVERY_SECONDS",
  trafficConfig.overload_recovery_seconds || 300
);

// VU sizing matches the lesson_bell convention: pre-allocate generously
// against the peak rate so that drops come from server saturation, not VU
// starvation.  Sized against peak_rate (not recovery_rate) because the
// overload phase is where queueing is heaviest.
const preAllocatedVUs = envInt(
  "INGEST_PRE_ALLOCATED_VUS",
  trafficConfig.ingest_pre_allocated_vus || Math.max(40, peakRate * 3)
);
const maxVUs = envInt(
  "INGEST_MAX_VUS",
  trafficConfig.ingest_max_vus || Math.max(preAllocatedVUs * 2, peakRate * 6)
);


export const options = {
  scenarios: {
    overload_recovery: {
      executor: "ramping-arrival-rate",
      startRate: 0,
      timeUnit: "1s",
      preAllocatedVUs,
      maxVUs,
      stages: [
        { duration: `${rampSeconds}s`, target: peakRate },
        { duration: `${holdSeconds}s`, target: peakRate },
        { duration: `${dropSeconds}s`, target: recoveryRate },
        { duration: `${recoverySeconds}s`, target: recoveryRate },
      ],
      tags: { traffic_class: "ingest", endpoint_group: "runs_ingest" },
    },
  },
  thresholds: {
    // Overload tolerances are loose — drops and 5xx are expected during the
    // hold phase, and that is fine; the thesis question is about recovery,
    // not steady-state behaviour at 2x capacity. Tighten if you want a
    // hard pass on the recovery phase specifically.
    "http_req_failed": ["rate<0.10"],
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
      "overload closed-week ingest rejected": (value) => value.status === 409,
    });
    return;
  }

  check(response, {
    "overload ingest accepted": (value) => [200, 201, 202].includes(value.status),
  });
}
