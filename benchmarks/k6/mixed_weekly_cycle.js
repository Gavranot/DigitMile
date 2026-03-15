import { check, sleep } from "k6";
import http from "k6/http";

import {
  authenticateTeacher,
  baseUrl,
  buildUnityPayload,
  envFloat,
  envInt,
  fetchApiCsrf,
  loadDatasetReport,
  loadScenarioConfig,
  pickDashboardParams,
  randomChoice,
  requestHeaders,
} from "./common.js";


export const options = {
  vus: Math.max(envInt("VUS_PLAYERS", 5), envInt("VUS_TEACHERS", 3)),
  duration: __ENV.DURATION || "60s",
};


const datasetReport = loadDatasetReport();
const scenarioConfig = loadScenarioConfig();


export function setup() {
  return {
    auth: authenticateTeacher(),
    csrf: fetchApiCsrf(),
  };
}


export default function (setupData) {
  const ingestTargets = datasetReport.ingest_targets || [];
  const replayRunIds = datasetReport.replay_run_ids || [];
  const replayRatio = envFloat("HOT_REPLAY_RATIO", (scenarioConfig.traffic || {}).hot_replay_ratio || 0.3);
  const actionRoll = Math.random();
  const headers = requestHeaders({ Cookie: setupData.auth.cookieHeader });

  if (actionRoll < 0.4) {
    const ingestResponse = http.post(
      `${baseUrl()}/panel/api/runs/ingest/`,
      JSON.stringify(buildUnityPayload(randomChoice(ingestTargets))),
      {
        headers: requestHeaders({
          "Content-Type": "application/json",
          "X-CSRFToken": setupData.csrf.csrfToken,
          Cookie: setupData.csrf.cookieHeader,
        }),
      }
    );
    check(ingestResponse, { "mixed ingest ok": (value) => [200, 201, 409].includes(value.status) });
  } else if (actionRoll < 0.75) {
    const query = pickDashboardParams(datasetReport, scenarioConfig.traffic || {});
    const dashboardResponse = http.get(`${baseUrl()}/panel/teacher/statistics/${query}`, { headers });
    check(dashboardResponse, { "mixed dashboard ok": (value) => value.status === 200 });
  } else {
    const runId = randomChoice(replayRunIds);
    const replayResponse = http.get(`${baseUrl()}/panel/teacher/runs/${runId}/`, { headers });
    check(replayResponse, { "mixed replay ok": (value) => value.status === 200 });
    if (Math.random() < replayRatio) {
      const analyticsResponse = http.get(`${baseUrl()}/panel/teacher/statistics/viz-data/?section=analytics`, { headers });
      check(analyticsResponse, { "mixed analytics ok": (value) => value.status === 200 });
    }
  }

  sleep(1);
}
