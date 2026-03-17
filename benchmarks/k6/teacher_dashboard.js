import { check } from "k6";
import http from "k6/http";

import {
  authenticateTeacher,
  baseUrl,
  envInt,
  loadDatasetReport,
  loadScenarioConfig,
  pickDashboardParams,
  requestHeaders,
} from "./common.js";


const datasetReport = loadDatasetReport();
const scenarioConfig = loadScenarioConfig();
const useArrivalRate = (__ENV.USE_ARRIVAL_RATE || "0") === "1";


export const options = useArrivalRate
  ? {
      scenarios: {
        default: {
          executor: "constant-arrival-rate",
          rate: envInt("DASHBOARD_RATE_PER_SEC", 4),
          timeUnit: "1s",
          duration: __ENV.DURATION || "30s",
          preAllocatedVUs: envInt("DASHBOARD_PRE_ALLOCATED_VUS", 4),
          maxVUs: envInt("DASHBOARD_MAX_VUS", 8),
        },
      },
    }
  : {
      vus: envInt("VUS_TEACHERS", 3),
      duration: __ENV.DURATION || "30s",
    };


export function setup() {
  return authenticateTeacher();
}


export default function (auth) {
  const query = pickDashboardParams(datasetReport, scenarioConfig.traffic || {});
  const headers = requestHeaders({ Cookie: auth.cookieHeader });
  const dashboardResponse = http.get(`${baseUrl()}/panel/teacher/statistics/${query}`, {
    headers,
    tags: { traffic_class: "dashboard", endpoint_group: "teacher_statistics_page" },
  });
  const analyticsResponse = http.get(
    `${baseUrl()}/panel/teacher/statistics/viz-data/?section=analytics${query ? `&${query.slice(1)}` : ""}`,
    {
      headers,
      tags: { traffic_class: "analytics", endpoint_group: "teacher_statistics_viz_analytics" },
    }
  );
  const insightsResponse = http.get(
    `${baseUrl()}/panel/teacher/statistics/viz-data/?section=turn_insights${query ? `&${query.slice(1)}` : ""}`,
    {
      headers,
      tags: { traffic_class: "turn_insights", endpoint_group: "teacher_statistics_viz_turn_insights" },
    }
  );

  check(dashboardResponse, { "dashboard page ok": (value) => value.status === 200 });
  check(analyticsResponse, { "analytics json ok": (value) => value.status === 200 });
  check(insightsResponse, { "turn insights json ok": (value) => value.status === 200 });
}
