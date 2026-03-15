import http from "k6/http";


export function envInt(name, fallbackValue) {
  return Number.parseInt(__ENV[name] || String(fallbackValue), 10);
}


export function envFloat(name, fallbackValue) {
  return Number.parseFloat(__ENV[name] || String(fallbackValue));
}


export function baseUrl() {
  return (__ENV.BASE_URL || "http://host.docker.internal").replace(/\/$/, "");
}


export function loadDatasetReport() {
  if (!__ENV.DATASET_REPORT) {
    return {};
  }
  return JSON.parse(open(__ENV.DATASET_REPORT));
}


export function loadScenarioConfig() {
  if (!__ENV.SCENARIO_CONFIG) {
    return {};
  }
  return JSON.parse(open(__ENV.SCENARIO_CONFIG));
}


export function randomChoice(values) {
  return values[Math.floor(Math.random() * values.length)];
}


export function requestHeaders(extraHeaders) {
  const headers = {};
  if (__ENV.REQUEST_HOST_HEADER) {
    headers.Host = __ENV.REQUEST_HOST_HEADER;
  }
  Object.keys(extraHeaders || {}).forEach((key) => {
    headers[key] = extraHeaders[key];
  });
  return headers;
}


function extractCsrfToken(html) {
  const match = html.match(/name=["']csrfmiddlewaretoken["']\s+value=["']([^"']+)["']/i);
  return match ? match[1] : "";
}


function cookieHeaderFromResponse(response) {
  const parts = [];
  Object.keys(response.cookies || {}).forEach((name) => {
    const values = response.cookies[name];
    if (values && values.length > 0) {
      parts.push(`${name}=${values[0].value}`);
    }
  });
  return parts.join("; ");
}


export function authenticateTeacher() {
  if (__ENV.SESSION_COOKIE) {
    return { cookieHeader: __ENV.SESSION_COOKIE };
  }

  const username = __ENV.TEACHER_USERNAME;
  const password = __ENV.TEACHER_PASSWORD;
  if (!username || !password) {
    throw new Error("Set SESSION_COOKIE or TEACHER_USERNAME/TEACHER_PASSWORD");
  }

  const loginUrl = `${baseUrl()}/panel/admin/login/?next=/panel/teacher/statistics/`;
  const loginPage = http.get(loginUrl, { headers: requestHeaders({}) });
  const csrfToken = extractCsrfToken(loginPage.body);
  const cookieHeader = cookieHeaderFromResponse(loginPage);
  const loginResponse = http.post(
    loginUrl,
    {
      username,
      password,
      next: "/panel/teacher/statistics/",
      csrfmiddlewaretoken: csrfToken,
    },
    {
      headers: requestHeaders({ Referer: loginUrl, Cookie: cookieHeader }),
      redirects: 0,
    }
  );
  return {
    cookieHeader: `${cookieHeader}; ${cookieHeaderFromResponse(loginResponse)}`,
  };
}


export function fetchApiCsrf() {
  const response = http.get(`${baseUrl()}/panel/api/fetchCSRFToken/`, {
    headers: requestHeaders({}),
  });
  const token = response.json("csrfToken");
  return {
    csrfToken: token,
    cookieHeader: cookieHeaderFromResponse(response),
  };
}


export function buildUnityPayload(target) {
  const startedAt = Date.now();
  const finishedAt = startedAt + 25000;
  return {
    classroomKey: target.classroom_key,
    user: target.student_name,
    userID: target.student_id,
    run: {
      runId: "",
      level: 5,
      score: 140,
      place: 1,
      correct_moves: 2,
      wrong_moves: 1,
      runStartedUnixMs: startedAt,
      runEndedUnixMs: finishedAt,
      gameMap: {
        mapTiles: [
          { tileMapIndex: 0, tileIndex: 0, tileType: 0, special: "normal", special_delta: 0 },
          { tileMapIndex: 1, tileIndex: 1, tileType: 1, special: "normal", special_delta: 0 },
          { tileMapIndex: 2, tileIndex: 4, tileType: 4, special: "clown", special_delta: -4 },
          { tileMapIndex: 3, tileIndex: 5, tileType: 5, special: "skateboard", special_delta: 5 },
        ],
      },
      turns: [
        {
          runId: "",
          turnIndex: 0,
          timestampPlayedUnixMs: startedAt + 1000,
          chosenCard: { type: "MoveX", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=1, elseValue=]" },
          wasCorrect: true,
          offeredCards: [
            { type: "MoveX", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=1, elseValue=]" },
            { type: "IfXMoveYElseMoveZ", data: "[CardData: tileType=1, ifSign=, ifValue=, thenValue=2, elseValue=1]" },
          ],
          playerPositionBefore: { placeRelativeToBots: 2, tileMapIndex: 0 },
          playerPositionAfter: { placeRelativeToBots: 1, tileMapIndex: 1 },
          botPositionsBefore: [],
          botPositionsAfter: [],
          tileBefore: { tileMapIndex: 0, tileIndex: 0, tileType: 0, special: "normal", special_delta: 0 },
          cardDecisionTimeMs: 1200,
          offeredNumbers: [2, 3, 4],
          chosenNumber: 3,
          numberDecisionTimeMs: 600,
          specialTileTriggers: [],
        },
        {
          runId: "",
          turnIndex: 1,
          timestampPlayedUnixMs: startedAt + 2500,
          chosenCard: { type: "Back", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=2, elseValue=]" },
          wasCorrect: false,
          offeredCards: [
            { type: "Back", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=2, elseValue=]" },
            { type: "BagCount", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]" },
          ],
          playerPositionBefore: { placeRelativeToBots: 1, tileMapIndex: 1 },
          playerPositionAfter: { placeRelativeToBots: 2, tileMapIndex: 2 },
          botPositionsBefore: [],
          botPositionsAfter: [],
          tileBefore: { tileMapIndex: 1, tileIndex: 1, tileType: 1, special: "normal", special_delta: 0 },
          cardDecisionTimeMs: 1500,
          offeredNumbers: [1, 3, 5],
          chosenNumber: 5,
          numberDecisionTimeMs: 900,
          specialTileTriggers: [
            {
              chainIndex: 0,
              specialTile: { tileMapIndex: 2, tileIndex: 4, tileType: 4, special: "clown", special_delta: -4 },
              positionOnSpecialTile: { placeRelativeToBots: 2, tileMapIndex: 2 },
              effectDeltaTiles: -4,
              positionAfterEffect: { placeRelativeToBots: 3, tileMapIndex: 0 },
            },
          ],
        },
      ],
    },
  };
}


export function pickDashboardParams(datasetReport, scenarioConfig) {
  const classrooms = datasetReport.classrooms || [];
  const selectedClassroom = classrooms.length > 0 ? randomChoice(classrooms) : null;
  const gradeFilterRatio = envFloat("GRADE_FILTER_RATIO", scenarioConfig.grade_filter_ratio || 0.3);
  const classroomFilterRatio = envFloat("CLASSROOM_FILTER_RATIO", scenarioConfig.classroom_filter_ratio || 0.3);
  const params = [];
  if (selectedClassroom && Math.random() < gradeFilterRatio) {
    params.push(`grade=${selectedClassroom.grade}`);
  }
  if (selectedClassroom && Math.random() < classroomFilterRatio) {
    params.push(`classroom=${selectedClassroom.classroom_id}`);
  }
  return params.length > 0 ? `?${params.join("&")}` : "";
}
