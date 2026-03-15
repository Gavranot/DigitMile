import { check, sleep } from "k6";
import http from "k6/http";

import { baseUrl, buildUnityPayload, envInt, fetchApiCsrf, loadDatasetReport, randomChoice, requestHeaders } from "./common.js";


export const options = {
  vus: envInt("VUS_PLAYERS", 5),
  duration: __ENV.DURATION || "30s",
};


const datasetReport = loadDatasetReport();


export default function () {
  const targets = datasetReport.ingest_targets || [];
  if (targets.length === 0) {
    throw new Error("No ingest targets found in DATASET_REPORT");
  }

  const csrf = fetchApiCsrf();
  const response = http.post(
    `${baseUrl()}/panel/api/runs/ingest/`,
    JSON.stringify(buildUnityPayload(randomChoice(targets))),
    {
      headers: requestHeaders({
        "Content-Type": "application/json",
        "X-CSRFToken": csrf.csrfToken,
        Cookie: csrf.cookieHeader,
      }),
    }
  );

  check(response, {
    "ingest succeeds": (value) => [200, 201, 409].includes(value.status),
  });
  sleep(1);
}
