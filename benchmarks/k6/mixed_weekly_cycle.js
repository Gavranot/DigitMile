import { check } from "k6";
import http from "k6/http";


import {
  authenticateTeacher,
  baseUrl,
  benchmarkHeaders,
  buildUnityPayload,
  envFloat,
  envInt,
  fetchApiCsrf,
  loadDatasetReport,
  loadScenarioConfig,
  pickDashboardParams,
  pickReplayRunId,
  randomChoice,
  requestHeaders,
} from "./common.js";


const datasetReport = loadDatasetReport();
const scenarioConfig = loadScenarioConfig();
const trafficConfig = scenarioConfig.traffic || {};
const expectedMode = __ENV.INGEST_EXPECTED_MODE || trafficConfig.ingest_expected_mode || "accepted";

// ramp_mode: when true, each traffic class uses ramping-arrival-rate from 0 to the configured
// target rate over the full duration instead of a constant rate.  Set via RAMP_MODE=1 env var
// or traffic.ramp_mode: true in the scenario JSON.  The stress_ramp scenario uses this to find
// the break-point: early in the run latency is fast, drops appear once the rate exceeds capacity.
const rampMode = __ENV.RAMP_MODE === "1" || trafficConfig.ramp_mode === true || trafficConfig.ramp_mode === "1";


function configuredRate(envName, configKey, fallbackValue) {
  const configuredValue = trafficConfig[configKey];
  return envInt(envName, configuredValue === undefined ? fallbackValue : configuredValue);
}


function configuredFloat(envName, configKey, fallbackValue) {
  const configuredValue = trafficConfig[configKey];
  return envFloat(envName, configuredValue === undefined ? fallbackValue : configuredValue);
}


function arrivalScenario(rate, execName, trafficClass, endpointGroup, minPreAllocated, expectedDurationSeconds) {
  if (rate <= 0) {
    return null;
  }

  // VU sizing via Little's Law: VUs = rate x response_time x headroom.
  // expectedDurationSeconds is the expected per-request response time in seconds.
  // Override per traffic class via <CLASS>_PRE_ALLOCATED_VUS / <CLASS>_MAX_VUS env vars
  // or the matching scenario JSON fields (passed through by run_scenario.py).
  const preAllocatedVUs = envInt(
    `${trafficClass.toUpperCase()}_PRE_ALLOCATED_VUS`,
    Math.max(minPreAllocated, Math.ceil(rate * expectedDurationSeconds * 1.5))
  );
  const maxVUs = envInt(
    `${trafficClass.toUpperCase()}_MAX_VUS`,
    Math.max(preAllocatedVUs * 2, Math.ceil(rate * expectedDurationSeconds * 3))
  );

  const duration = __ENV.DURATION || trafficConfig.duration || "60s";
  const tags = { traffic_class: trafficClass, endpoint_group: endpointGroup };

  if (rampMode) {
    // Ramp from 0 to target rate linearly over the full duration.
    // Early iterations will complete quickly; drops appear once rate exceeds server capacity.
    // This reveals the break-point rather than just saturating the server immediately.
    return {
      executor: "ramping-arrival-rate",
      startRate: 0,
      timeUnit: "1s",
      preAllocatedVUs,
      maxVUs,
      stages: [{ duration, target: rate }],
      exec: execName,
      tags,
    };
  }

  return {
    executor: "constant-arrival-rate",
    rate,
    timeUnit: "1s",
    duration,
    preAllocatedVUs,
    maxVUs,
    exec: execName,
    tags,
  };
}


const scenarios = {};

const ingestScenario = arrivalScenario(
  configuredRate("INGEST_RATE_PER_SEC", "ingest_rate_per_sec", 8),
  "ingestWriters",
  "ingest",
  "runs_ingest",
  8,
  configuredFloat("INGEST_EXPECTED_DURATION_SECONDS", "ingest_expected_duration_seconds", 2)
);
if (ingestScenario) {
  scenarios.ingest_writers = ingestScenario;
}

const dashboardScenario = arrivalScenario(
  configuredRate("DASHBOARD_RATE_PER_SEC", "dashboard_rate_per_sec", 4),
  "dashboardReaders",
  "dashboard",
  "teacher_statistics_page",
  4,
  configuredFloat("DASHBOARD_EXPECTED_DURATION_SECONDS", "dashboard_expected_duration_seconds", 5)
);
if (dashboardScenario) {
  scenarios.dashboard_readers = dashboardScenario;
}

const analyticsScenario = arrivalScenario(
  configuredRate("ANALYTICS_RATE_PER_SEC", "analytics_rate_per_sec", 3),
  "analyticsReaders",
  "analytics",
  "teacher_statistics_viz_analytics",
  3,
  configuredFloat("ANALYTICS_EXPECTED_DURATION_SECONDS", "analytics_expected_duration_seconds", 6)
);
if (analyticsScenario) {
  scenarios.analytics_readers = analyticsScenario;
}

const turnInsightsScenario = arrivalScenario(
  configuredRate("TURN_INSIGHTS_RATE_PER_SEC", "turn_insights_rate_per_sec", 3),
  "turnInsightsReaders",
  "turn_insights",
  "teacher_statistics_viz_turn_insights",
  3,
  configuredFloat("TURN_INSIGHTS_EXPECTED_DURATION_SECONDS", "turn_insights_expected_duration_seconds", 6)
);
if (turnInsightsScenario) {
  scenarios.turn_insights_readers = turnInsightsScenario;
}

const replayScenario = arrivalScenario(
  configuredRate("REPLAY_RATE_PER_SEC", "replay_rate_per_sec", 2),
  "replayReaders",
  "replay",
  "teacher_run_replay",
  2,
  configuredFloat("REPLAY_EXPECTED_DURATION_SECONDS", "replay_expected_duration_seconds", 4)
);
if (replayScenario) {
  scenarios.replay_readers = replayScenario;
}


export const options = { scenarios };


export function setup() {
  return {
    auth: authenticateTeacher(),
    csrf: fetchApiCsrf(),
  };
}


function dashboardQuery() {
  return pickDashboardParams(datasetReport, trafficConfig);
}


export function ingestWriters(setupData) {
  const ingestTargets = datasetReport.ingest_targets_hot_week || datasetReport.ingest_targets || [];
  if (ingestTargets.length === 0) {
    throw new Error("No ingest targets found in DATASET_REPORT");
  }

  const response = http.post(
    `${baseUrl()}/panel/api/runs/ingest/`,
    JSON.stringify(buildUnityPayload(randomChoice(ingestTargets), datasetReport)),
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
    check(response, { "mixed closed-week ingest rejected": (value) => value.status === 409 });
    return;
  }

  check(response, { "mixed open-week ingest accepted": (value) => [200, 201, 202].includes(value.status) });
}


export function dashboardReaders(setupData) {
  const response = http.get(`${baseUrl()}/panel/teacher/statistics/${dashboardQuery()}`, {
    headers: requestHeaders({ Cookie: setupData.auth.cookieHeader }),
    tags: {
      traffic_class: "dashboard",
      endpoint_group: "teacher_statistics_page",
    },
  });
  check(response, { "mixed dashboard ok": (value) => value.status === 200 });
}


export function analyticsReaders(setupData) {
  const query = dashboardQuery();
  const response = http.get(
    `${baseUrl()}/panel/teacher/statistics/viz-data/?section=analytics${query ? `&${query.slice(1)}` : ""}`,
    {
      headers: requestHeaders({ Cookie: setupData.auth.cookieHeader }),
      tags: {
        traffic_class: "analytics",
        endpoint_group: "teacher_statistics_viz_analytics",
      },
    }
  );
  check(response, { "mixed analytics ok": (value) => value.status === 200 });
}


export function turnInsightsReaders(setupData) {
  const query = dashboardQuery();
  const response = http.get(
    `${baseUrl()}/panel/teacher/statistics/viz-data/?section=turn_insights${query ? `&${query.slice(1)}` : ""}`,
    {
      headers: requestHeaders({ Cookie: setupData.auth.cookieHeader }),
      tags: {
        traffic_class: "turn_insights",
        endpoint_group: "teacher_statistics_viz_turn_insights",
      },
    }
  );
  check(response, { "mixed turn insights ok": (value) => value.status === 200 });
}


export function replayReaders(setupData) {
  const response = http.get(
    `${baseUrl()}/panel/teacher/runs/${pickReplayRunId(datasetReport, envFloat("HOT_REPLAY_RATIO", trafficConfig.hot_replay_ratio || 0.3))}/`,
    {
      headers: requestHeaders({ Cookie: setupData.auth.cookieHeader }),
      tags: {
        traffic_class: "replay",
        endpoint_group: "teacher_run_replay",
      },
    }
  );
  check(response, { "mixed replay ok": (value) => value.status === 200 });
}
