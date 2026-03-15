import { check, sleep } from "k6";
import http from "k6/http";

import { authenticateTeacher, baseUrl, envInt, loadDatasetReport, randomChoice, requestHeaders } from "./common.js";


export const options = {
  vus: envInt("VUS_TEACHERS", 3),
  duration: __ENV.DURATION || "30s",
};


const datasetReport = loadDatasetReport();


export function setup() {
  return authenticateTeacher();
}


export default function (auth) {
  const runIds = datasetReport.replay_run_ids || [];
  if (runIds.length === 0) {
    throw new Error("No replay run ids found in DATASET_REPORT");
  }

  const response = http.get(
    `${baseUrl()}/panel/teacher/runs/${randomChoice(runIds)}/`,
    { headers: requestHeaders({ Cookie: auth.cookieHeader }) }
  );
  check(response, { "replay page ok": (value) => value.status === 200 });
  sleep(1);
}
