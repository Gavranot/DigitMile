import http from "k6/http";


export function envInt(name, fallbackValue) {
  return Number.parseInt(__ENV[name] || String(fallbackValue), 10);
}


export function envFloat(name, fallbackValue) {
  return Number.parseFloat(__ENV[name] || String(fallbackValue));
}


export function baseUrl() {
  return (__ENV.BASE_URL || "http://digitmile-backend:8000").replace(/\/$/, "");
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


function randomInt(minValue, maxValue) {
  return Math.floor(Math.random() * (maxValue - minValue + 1)) + minValue;
}


function parseIsoToMs(value) {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    throw new Error(`Unable to parse ISO datetime: ${value}`);
  }
  return parsed;
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


export function benchmarkHeaders(datasetReport, extraHeaders) {
  const headers = requestHeaders(extraHeaders || {});
  const referenceTime = __ENV.BENCHMARK_REFERENCE_TIME || datasetReport.synthetic_now;
  if (referenceTime) {
    headers["X-Benchmark-Reference-Time"] = referenceTime;
  }
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


export function syntheticClock(datasetReport) {
  if (!datasetReport.hot_week_start || !datasetReport.synthetic_now) {
    throw new Error("DATASET_REPORT is missing synthetic hot-week metadata");
  }

  const hotWeekStartMs = parseIsoToMs(`${datasetReport.hot_week_start}T08:00:00Z`);
  const syntheticNowMs = parseIsoToMs(__ENV.BENCHMARK_REFERENCE_TIME || datasetReport.synthetic_now);
  const upperBoundMs = Math.max(hotWeekStartMs + 60000, syntheticNowMs - 60000);

  return {
    hotWeekStartMs,
    syntheticNowMs,
    upperBoundMs,
  };
}


export function pickSyntheticRunWindow(datasetReport) {
  const clock = syntheticClock(datasetReport);
  const startedAt = randomInt(clock.hotWeekStartMs, clock.upperBoundMs);
  const durationMs = randomInt(18000, 42000);
  const finishedAt = Math.min(startedAt + durationMs, clock.syntheticNowMs - 1000);
  return {
    startedAt,
    finishedAt: Math.max(startedAt + 1000, finishedAt),
  };
}


function benchmarkRunId(startedAt) {
  const parts = [startedAt, __VU, __ITER, randomInt(0, 0xffffffff)];
  const hex = parts
    .map((value) => Math.abs(Number(value)).toString(16))
    .join("")
    .replace(/[^0-9a-f]/gi, "")
    .slice(0, 32)
    .padEnd(32, "0");
  return `run_${hex}`;
}


// Per-level turn-count distribution. Mirrors LEVEL_TURN_DISTRIBUTION in
// DigitMilePanel/digitmileapi/management/commands/prepare_benchmark_dataset.py
// so synthetic payloads match seeded data shape.  Anchored on
// docs/research/ingest-capacity-model.md §2.3 (T = 20, bracket means 18/20/22).
export const LEVEL_TURN_DISTRIBUTION = {
  1: { mean: 17, std: 2.0, min: 12, max: 22 },
  2: { mean: 19, std: 2.0, min: 12, max: 23 },
  3: { mean: 19, std: 2.5, min: 12, max: 24 },
  4: { mean: 21, std: 2.5, min: 12, max: 25 },
  5: { mean: 21, std: 3.0, min: 12, max: 27 },
  6: { mean: 23, std: 3.0, min: 12, max: 28 },
};


function sampleGaussian(mean, std) {
  // Box-Muller. Guard Math.random()==0 producing -Infinity.
  const u1 = Math.max(Math.random(), 1e-12);
  const u2 = Math.random();
  return mean + std * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}


export function sampleTurnCount(level, scale) {
  const profile = LEVEL_TURN_DISTRIBUTION[level] || LEVEL_TURN_DISTRIBUTION[1];
  const turnScale = scale == null ? 1.0 : scale;
  const mean = profile.mean * turnScale;
  const std = Math.max(0.5, profile.std * turnScale);
  const floor = Math.max(2, Math.round(profile.min * turnScale));
  const ceiling = Math.max(floor, Math.round(profile.max * turnScale));
  const sample = sampleGaussian(mean, std);
  return Math.max(floor, Math.min(ceiling, Math.round(sample)));
}


export function pickLevel(bagLevelRatio) {
  const ratio = bagLevelRatio == null ? 0.35 : bagLevelRatio;
  if (Math.random() < ratio) {
    return Math.random() < 0.5 ? 5 : 6;
  }
  return [1, 2, 3, 4][Math.floor(Math.random() * 4)];
}


const CARD_TEMPLATES = [
  { type: "MoveX", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=2, elseValue=]" },
  { type: "IfXMoveYElseMoveZ", data: "[CardData: tileType=1, ifSign=, ifValue=, thenValue=2, elseValue=1]" },
  { type: "Back", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=2, elseValue=]" },
  { type: "ForXMoveY", data: "[CardData: tileType=1, ifSign=, ifValue=, thenValue=2, elseValue=]" },
];
const BAG_CARD_TEMPLATES = [
  { type: "IfBagEqualXMoveYElseMoveZ", data: "[CardData: tileType=, ifSign===, ifValue=3, thenValue=2, elseValue=1]" },
  { type: "IfBagLessXMoveYElseMoveZ", data: "[CardData: tileType=, ifSign=<, ifValue=4, thenValue=3, elseValue=1]" },
  { type: "BagCount", data: "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]" },
];

const MAP_TILES = [
  { tileMapIndex: 0, tileIndex: 0, tileType: 0, special: "normal", special_delta: 0 },
  { tileMapIndex: 1, tileIndex: 1, tileType: 1, special: "normal", special_delta: 0 },
  { tileMapIndex: 2, tileIndex: 4, tileType: 4, special: "clown", special_delta: -4 },
  { tileMapIndex: 3, tileIndex: 5, tileType: 5, special: "skateboard", special_delta: 5 },
];


function buildTurn(turnIndex, level, prevPos, timestampMs, isCorrect, specialChance) {
  const pool = level >= 5 ? CARD_TEMPLATES.concat(BAG_CARD_TEMPLATES) : CARD_TEMPLATES;
  const chosen = pool[Math.floor(Math.random() * pool.length)];
  const offered = [{ type: chosen.type, data: chosen.data }];
  while (offered.length < 3) {
    const next = pool[Math.floor(Math.random() * pool.length)];
    offered.push({ type: next.type, data: next.data });
  }

  const movement = isCorrect ? 1 + Math.floor(Math.random() * 3) : 1;
  const newPos = (prevPos + movement) % 60;
  const placeBefore = 1 + Math.floor(Math.random() * 3);
  const placeAfter = Math.max(1, Math.min(4, placeBefore + (isCorrect ? -1 : 1)));

  const tileBefore = MAP_TILES[prevPos % MAP_TILES.length];
  const turn = {
    turnIndex,
    timestampPlayedUnixMs: timestampMs,
    chosenCard: { type: chosen.type, data: chosen.data },
    wasCorrect: isCorrect,
    offeredCards: offered,
    playerPositionBefore: { placeRelativeToBots: placeBefore, tileMapIndex: prevPos % MAP_TILES.length },
    playerPositionAfter: { placeRelativeToBots: placeAfter, tileMapIndex: newPos % MAP_TILES.length },
    botPositionsBefore: [],
    botPositionsAfter: [],
    tileBefore,
    cardDecisionTimeMs: 800 + Math.floor(Math.random() * 1800),
    offeredNumbers: level >= 5 ? [1 + Math.floor(Math.random() * 5), 1 + Math.floor(Math.random() * 5), 1 + Math.floor(Math.random() * 5)] : [],
    chosenNumber: level >= 5 ? 1 + Math.floor(Math.random() * 5) : -1,
    numberDecisionTimeMs: level >= 5 ? 400 + Math.floor(Math.random() * 1500) : -1,
    specialTileTriggers: [],
  };

  if (Math.random() < specialChance) {
    const delta = Math.random() < 0.5 ? -4 : 5;
    const targetPos = Math.max(0, (newPos + delta + 60) % 60);
    turn.specialTileTriggers.push({
      chainIndex: 0,
      specialTile: delta < 0 ? MAP_TILES[2] : MAP_TILES[3],
      positionOnSpecialTile: { placeRelativeToBots: placeAfter, tileMapIndex: newPos % MAP_TILES.length },
      effectDeltaTiles: delta,
      positionAfterEffect: { placeRelativeToBots: Math.max(1, Math.min(4, placeAfter + (delta < 0 ? 1 : -1))), tileMapIndex: targetPos % MAP_TILES.length },
    });
  }

  return { turn, newPos };
}


// buildUnityPayload — generates a schema-valid Unity ingest payload with
// realistic turn count and level mix.
//
// Options (all optional, fall through to env vars):
//   level                 fixed level 1..6 (env: INGEST_FIXED_LEVEL — 0 = sample)
//   turnScale             scales per-level mean/std/min/max uniformly
//                         (env: INGEST_TURN_SCALE, default 1.0)
//   bagLevelRatio         P(level ∈ {5,6}) for level sampling
//                         (env: INGEST_BAG_LEVEL_RATIO, default 0.35)
//   specialChance         per-turn probability of a SpecialTileTrigger
//                         (env: INGEST_SPECIAL_TILE_CHANCE, default 0.05)
//   correctChance         per-turn probability of wasCorrect=true
//                         (env: INGEST_CORRECT_CHANCE, default 0.72)
export function buildUnityPayload(target, datasetReport, options) {
  const opts = options || {};
  const turnScale = opts.turnScale != null ? opts.turnScale : envFloat("INGEST_TURN_SCALE", 1.0);
  const bagLevelRatio = opts.bagLevelRatio != null ? opts.bagLevelRatio : envFloat("INGEST_BAG_LEVEL_RATIO", 0.35);
  const specialChance = opts.specialChance != null ? opts.specialChance : envFloat("INGEST_SPECIAL_TILE_CHANCE", 0.05);
  const correctChance = opts.correctChance != null ? opts.correctChance : envFloat("INGEST_CORRECT_CHANCE", 0.72);
  const forcedLevel = opts.level != null ? opts.level : envInt("INGEST_FIXED_LEVEL", 0);
  const level = forcedLevel > 0 ? forcedLevel : pickLevel(bagLevelRatio);
  const turnCount = sampleTurnCount(level, turnScale);

  const window = pickSyntheticRunWindow(datasetReport);
  const runId = benchmarkRunId(window.startedAt);

  const spanMs = Math.max(turnCount * 1000, window.finishedAt - window.startedAt - 1000);
  const turnInterval = Math.max(500, Math.floor(spanMs / turnCount));

  let pos = 0;
  let timestamp = window.startedAt + 1000;
  let correctFromTurns = 0;
  const turns = [];
  for (let i = 0; i < turnCount; i++) {
    const isCorrect = Math.random() < correctChance;
    if (isCorrect) correctFromTurns += 1;
    const built = buildTurn(i, level, pos, timestamp, isCorrect, specialChance);
    turns.push(built.turn);
    pos = built.newPos;
    timestamp += turnInterval;
  }

  // place == 1 (won) → validator expects correct_moves = correctFromTurns + 1.
  // wrong_moves = turnCount - correctFromTurns.
  const place = 1;
  const correctMoves = correctFromTurns + 1;
  const wrongMoves = turnCount - correctFromTurns;
  const score = 100 + correctFromTurns * 20;

  return {
    classroomKey: target.classroom_key,
    user: target.student_name,
    userID: target.student_id,
    run: {
      runId,
      level,
      score,
      place,
      correct_moves: correctMoves,
      wrong_moves: wrongMoves,
      runStartedUnixMs: window.startedAt,
      runEndedUnixMs: Math.max(window.finishedAt, timestamp + 500),
      gameMap: { mapTiles: MAP_TILES },
      turns,
    },
  };
}


export function pickDashboardParams(datasetReport, trafficConfig) {
  const classrooms = datasetReport.dashboard_filter_targets || datasetReport.classrooms || [];
  const selectedClassroom = classrooms.length > 0 ? randomChoice(classrooms) : null;
  const gradeFilterRatio = envFloat("GRADE_FILTER_RATIO", trafficConfig.grade_filter_ratio || 0.3);
  const classroomFilterRatio = envFloat("CLASSROOM_FILTER_RATIO", trafficConfig.classroom_filter_ratio || 0.3);
  const params = [];
  if (selectedClassroom && Math.random() < gradeFilterRatio) {
    params.push(`grade=${selectedClassroom.grade}`);
  }
  if (selectedClassroom && Math.random() < classroomFilterRatio) {
    params.push(`classroom=${selectedClassroom.classroom_id}`);
  }
  return params.length > 0 ? `?${params.join("&")}` : "";
}


export function pickReplayRunId(datasetReport, hotReplayRatio) {
  const hotTargets = datasetReport.replay_targets_hot || [];
  const coldTargets = datasetReport.replay_targets_cold || [];
  if (hotTargets.length > 0 && (coldTargets.length === 0 || Math.random() < hotReplayRatio)) {
    return randomChoice(hotTargets).run_id;
  }
  if (coldTargets.length > 0) {
    return randomChoice(coldTargets).run_id;
  }
  const replayRunIds = datasetReport.replay_run_ids || [];
  if (replayRunIds.length === 0) {
    throw new Error("No replay run ids found in DATASET_REPORT");
  }
  return randomChoice(replayRunIds);
}
