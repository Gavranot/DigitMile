import { check } from "k6";
import http from "k6/http";

import {
  authenticateTeacher,
  baseUrl,
  envFloat,
  envInt,
  loadDatasetReport,
  pickReplayRunId,
  requestHeaders,
} from "./common.js";


const datasetReport = loadDatasetReport();
const useArrivalRate = (__ENV.USE_ARRIVAL_RATE || "0") === "1";


export const options = useArrivalRate
  ? {
      scenarios: {
        default: {
          executor: "constant-arrival-rate",
          rate: envInt("REPLAY_RATE_PER_SEC", 3),
          timeUnit: "1s",
          duration: __ENV.DURATION || "30s",
          preAllocatedVUs: envInt("REPLAY_PRE_ALLOCATED_VUS", 3),
          maxVUs: envInt("REPLAY_MAX_VUS", 6),
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
  const response = http.get(
    `${baseUrl()}/panel/teacher/runs/${pickReplayRunId(datasetReport, envFloat("HOT_REPLAY_RATIO", 0.3))}/`,
    {
      headers: requestHeaders({ Cookie: auth.cookieHeader }),
      tags: { traffic_class: "replay", endpoint_group: "teacher_run_replay" },
    }
  );
  check(response, { "replay page ok": (value) => value.status === 200 });
}
