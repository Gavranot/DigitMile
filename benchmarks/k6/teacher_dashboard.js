import { check, sleep } from "k6";
import http from "k6/http";

import { authenticateTeacher, baseUrl, envInt, loadDatasetReport, loadScenarioConfig, pickDashboardParams, requestHeaders } from "./common.js";


export const options = {
  vus: envInt("VUS_TEACHERS", 3),
  duration: __ENV.DURATION || "30s",
};


const datasetReport = loadDatasetReport();
const scenarioConfig = loadScenarioConfig();


export function setup() {
  return authenticateTeacher();
}


export default function (auth) {
  const query = pickDashboardParams(datasetReport, scenarioConfig.traffic || {});
  const headers = { headers: requestHeaders({ Cookie: auth.cookieHeader }) };
  const dashboardResponse = http.get(`${baseUrl()}/panel/teacher/statistics/${query}`, headers);
  const analyticsResponse = http.get(`${baseUrl()}/panel/teacher/statistics/viz-data/?section=analytics${query ? `&${query.slice(1)}` : ""}`, headers);
  const insightsResponse = http.get(`${baseUrl()}/panel/teacher/statistics/viz-data/?section=turn_insights${query ? `&${query.slice(1)}` : ""}`, headers);

  check(dashboardResponse, { "dashboard page ok": (value) => value.status === 200 });
  check(analyticsResponse, { "analytics json ok": (value) => value.status === 200 });
  check(insightsResponse, { "turn insights json ok": (value) => value.status === 200 });
  sleep(1);
}
