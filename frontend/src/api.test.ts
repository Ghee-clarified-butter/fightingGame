import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMatch, getMatch, submitTurn } from "./api";
import { ApiError, type MatchState } from "./types";

/** A minimal but shape-correct §5.5 payload; the API module only passes it through. */
const STATE: MatchState = {
  match_id: "9f2c1e",
  status: "in_progress",
  turn: 0,
  player: {
    id: "kaito",
    name: "Kaito",
    hp: 100,
    hp_max: 100,
    ki: 30,
    ki_max: 100,
    atk: 22,
    def: 8,
    spd: 14,
    guarding: false,
    ascended: false,
    ascend_used: false,
    passive_streak: 0,
  },
  opponent: {
    id: "vega",
    name: "Vega",
    hp: 130,
    hp_max: 130,
    ki: 30,
    ki_max: 100,
    atk: 16,
    def: 14,
    spd: 9,
    guarding: false,
    ascended: false,
    ascend_used: false,
    passive_streak: 0,
  },
  legal_actions: ["strike", "charge", "guard"],
  log: [],
};

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The (url, init) pair of the single call the stub recorded. */
function callOf(fetchMock: ReturnType<typeof stubFetch>) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
  return { url, init };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createMatch", () => {
  it("POSTs the two fighter ids to the relative match path", async () => {
    const fetchMock = stubFetch(201, STATE);

    await expect(createMatch("kaito", "vega")).resolves.toEqual(STATE);

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/match");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      player_fighter: "kaito",
      opponent_fighter: "vega",
    });
  });

  it("omits seed when not given and sends it as an integer when it is", async () => {
    const fetchMock = stubFetch(201, STATE);

    await createMatch("kaito", "kaito", 12345);

    const { init } = callOf(fetchMock);
    expect(JSON.parse(String(init?.body))).toEqual({
      player_fighter: "kaito",
      opponent_fighter: "kaito",
      seed: 12345,
    });
  });
});

describe("getMatch", () => {
  it("GETs the relative match path for the given id", async () => {
    const fetchMock = stubFetch(200, STATE);

    await expect(getMatch("9f2c1e")).resolves.toEqual(STATE);

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/match/9f2c1e");
    expect(init?.method).toBe("GET");
    expect(init?.body).toBeUndefined();
  });
});

describe("submitTurn", () => {
  it("POSTs only the action to the relative turn path", async () => {
    const fetchMock = stubFetch(200, { ...STATE, turn: 1 });

    const state = await submitTurn("9f2c1e", "ki_blast");
    expect(state.turn).toBe(1);

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/match/9f2c1e/turn");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ action: "ki_blast" });
  });
});

describe("error handling", () => {
  it("surfaces a 400 envelope as an ApiError carrying code and message", async () => {
    stubFetch(400, {
      error: {
        code: "insufficient_ki",
        message: "Surge Beam costs 40 ki; Kaito has 25.",
      },
    });

    const error = await submitTurn("9f2c1e", "surge_beam").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("insufficient_ki");
    expect((error as ApiError).message).toBe("Surge Beam costs 40 ki; Kaito has 25.");
    expect((error as ApiError).status).toBe(400);
  });

  it("reports a 404 from GET as match_not_found", async () => {
    stubFetch(404, {
      error: { code: "match_not_found", message: "No match with id 'nope'." },
    });

    const error = await getMatch("nope").catch((e: unknown) => e);

    expect((error as ApiError).code).toBe("match_not_found");
    expect((error as ApiError).status).toBe(404);
  });

  it("still throws something readable when the error body is not the envelope", async () => {
    stubFetch(500, "<html>boom</html>");

    const error = await createMatch("kaito", "vega").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("unknown_error");
    expect((error as ApiError).message).toContain("500");
  });
});

describe("the module's URLs", () => {
  it("contains no absolute URL — every path goes through the Vite proxy", () => {
    // Vitest runs with the frontend package as its root.
    const source = readFileSync(join(process.cwd(), "src", "api.ts"), "utf8");
    const code = source.replace(/\/\*\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

    expect(code).not.toMatch(/https?:\/\//);
    expect(code).not.toMatch(/localhost/);
    expect(code).toContain('"/api/match"');
  });
});
