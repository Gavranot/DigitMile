import { check } from "k6";
import http from "k6/http";

import {
  baseUrl,
  benchmarkHeaders,
  buildUnityPayload,
  envInt,
  fetchApiCsrf,
  loadDatasetReport,
  randomChoice,
} from "./common.js";


const datasetReport = loadDatasetReport();
const expectedMode = __ENV.INGEST_EXPECTED_MODE || "accepted";
const useArrivalRate = (__ENV.USE_ARRIVAL_RATE || "0") === "1";


export const options = useArrivalRate
  ? {
      scenarios: {
        default: {
          executor: "constant-arrival-rate",
          rate: envInt("INGEST_RATE_PER_SEC", 8),
          timeUnit: "1s",
          duration: __ENV.DURATION || "30s",
          preAllocatedVUs: envInt("INGEST_PRE_ALLOCATED_VUS", 8),
          maxVUs: envInt("INGEST_MAX_VUS", 16),
        },
      },
    }
  : {
      vus: envInt("VUS_PLAYERS", 5),
      duration: __ENV.DURATION || "30s",
    };


export default function () {
  const targets = datasetReport.ingest_targets_hot_week || datasetReport.ingest_targets || [];
  if (targets.length === 0) {
    throw new Error("No ingest targets found in DATASET_REPORT");
  }

  const csrf = fetchApiCsrf();
  const response = http.post(
    `${baseUrl()}/panel/api/runs/ingest/`,
    JSON.stringify(buildUnityPayload(randomChoice(targets), datasetReport)),
    {
      headers: benchmarkHeaders(datasetReport, {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf.csrfToken,
        Cookie: csrf.cookieHeader,
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
      "closed-week ingest rejected": (value) => value.status === 409,
    });
    return;
  }

  check(response, {
    "open-week ingest accepted": (value) => [200, 201, 202].includes(value.status),
  });
}
