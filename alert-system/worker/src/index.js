import { codeForName, formatCode, normalizeName, topicForCode } from "./codes.js";
import { parseServiceAccount, sendToTopic } from "./fcm.js";
import { verifyAccessJwt } from "./access.js";
import { AlertHub, isTopic } from "./hub.js";

export { AlertHub };

const MAX_MESSAGE = 200;
const MAX_TARGETS = 50;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

class HttpError extends Error {
  constructor(status, message, extra = {}) {
    super(message);
    this.status = status;
    this.extra = extra;
  }
}

async function sameSecret(a, b) {
  // Compare digests so the time taken doesn't reveal how much of the password matched.
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([a, b].map(async (s) =>
    new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(s)))));
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

// Returns who is sending. Cloudflare Access (if configured) wins; otherwise a shared
// sender password that the page asks for once and remembers. With neither, refuse.
async function authenticate(request, env, fetchImpl) {
  if (env.DEV_NO_AUTH === "true") return "dev@localhost";
  if (env.ACCESS_TEAM_DOMAIN && env.ACCESS_AUD) {
    try {
      return await verifyAccessJwt(
        request.headers.get("cf-access-jwt-assertion"),
        { teamDomain: env.ACCESS_TEAM_DOMAIN, aud: env.ACCESS_AUD },
        fetchImpl,
      );
    } catch (e) {
      throw new HttpError(401, e.message);
    }
  }
  if (env.SEND_PASSWORD) {
    if (env.SEND_PASSWORD.length < 8) throw new HttpError(500, "SEND_PASSWORD must be at least 8 characters.");
    const given = request.headers.get("x-edith-password") || "";
    if (!given || !(await sameSecret(given, env.SEND_PASSWORD))) {
      throw new HttpError(401, given ? "wrong password" : "password needed", { auth: "password" });
    }
    const sender = (request.headers.get("x-edith-sender") || "").trim().replace(/\s+/g, " ").slice(0, 40);
    return sender || "Sender";
  }
  throw new HttpError(500, "No sender protection set. Run: npx wrangler secret put SEND_PASSWORD");
}

function requireSecret(env) {
  if (!env.CODE_SECRET || env.CODE_SECRET.length < 16) {
    throw new HttpError(500, "CODE_SECRET is not set (needs 16+ random characters).");
  }
  return env.CODE_SECRET;
}

async function readJson(request) {
  // JSON-only bodies force a CORS preflight, which this Worker never approves,
  // so other sites can't make a signed-in sender's browser fire alerts.
  if (!(request.headers.get("content-type") || "").includes("application/json")) {
    throw new HttpError(415, "expected application/json");
  }
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(request.url).origin) throw new HttpError(403, "cross-site request refused");
  try {
    return await request.json();
  } catch {
    throw new HttpError(400, "invalid JSON");
  }
}

function cleanNames(names) {
  if (!Array.isArray(names)) throw new HttpError(400, "names must be a list");
  const unique = new Map(); // normalized -> first spelling seen
  for (const n of names) {
    const key = normalizeName(n);
    if (key && !unique.has(key)) unique.set(key, String(n).trim());
  }
  if (unique.size === 0) throw new HttpError(400, "pick at least one phone");
  if (unique.size > MAX_TARGETS) throw new HttpError(400, `at most ${MAX_TARGETS} phones per alert`);
  return [...unique.values()];
}

async function sendAll(env, names, data, fetchImpl) {
  const secret = requireSecret(env);
  if (!env.FCM_SERVICE_ACCOUNT) throw new HttpError(500, "FCM_SERVICE_ACCOUNT is not set.");
  let sa;
  try {
    sa = parseServiceAccount(env.FCM_SERVICE_ACCOUNT);
  } catch (e) {
    throw new HttpError(500, e.message);
  }
  const topics = await Promise.all(names.map(async (name) => topicForCode(await codeForName(secret, name))));

  // Route 1: straight down each phone's own connection to this site (see hub.js).
  let connected = {};
  if (env.HUB) {
    try {
      const hub = env.HUB.get(env.HUB.idFromName("hub"));
      const res = await hub.fetch("https://hub/broadcast", {
        method: "POST",
        body: JSON.stringify({ topics, data }),
      });
      if (res.ok) connected = await res.json();
    } catch (e) {
      console.error("hub broadcast failed", e);
    }
  }

  // Route 2: Google push, which also reaches phones whose direct link is down.
  const results = await Promise.allSettled(topics.map((topic) => sendToTopic(sa, topic, data, fetchImpl)));

  const sent = [];
  const failed = [];
  const online = [];
  results.forEach((r, i) => {
    const live = (connected[topics[i]] || 0) > 0;
    if (live) online.push(names[i]);
    if (r.status === "fulfilled" || live) sent.push(names[i]);
    else failed.push({ name: names[i], error: String(r.reason?.message || r.reason) });
  });
  return { sent, failed, online };
}

export async function handleApi(request, env, fetchImpl = fetch) {
  const { pathname } = new URL(request.url);
  const email = await authenticate(request, env, fetchImpl);

  if (pathname === "/api/me" && request.method === "GET") {
    return json({ email, auth: env.ACCESS_TEAM_DOMAIN && env.ACCESS_AUD ? "access" : "password" });
  }

  if (pathname === "/api/code" && request.method === "POST") {
    const { name } = await readJson(request);
    const display = String(name ?? "").trim().replace(/\s+/g, " ");
    if (!display || display.length > 40) throw new HttpError(400, "name must be 1-40 characters");
    return json({ name: display, code: formatCode(await codeForName(requireSecret(env), display)) });
  }

  if (pathname === "/api/send" && request.method === "POST") {
    const body = await readJson(request);
    const names = cleanNames(body.names);
    const type = body.type === "stop" ? "stop" : "alert";
    const message = String(body.message ?? "").trim() || "EMERGENCY ALERT";
    if (message.length > MAX_MESSAGE) throw new HttpError(400, `message is over ${MAX_MESSAGE} characters`);
    const data = {
      type,
      id: crypto.randomUUID(),
      message: type === "alert" ? message : "",
      sender: email, // FCM rejects "from" (and google*/gcm* keys) in data payloads
      sent_at: String(Date.now()),
    };
    const result = await sendAll(env, names, data, fetchImpl);
    console.log(JSON.stringify({
      event: type, from: email, sent: result.sent.length, online: result.online.length, failed: result.failed.length,
    }));
    return json(result, result.sent.length ? 200 : 502);
  }

  throw new HttpError(404, "not found");
}

// Phones open a WebSocket here to get alerts directly. The topic is derived from the
// phone's secret code, so knowing it is the same as knowing the code.
export function handleListen(request, env) {
  const topic = new URL(request.url).searchParams.get("topic") || "";
  if (request.headers.get("upgrade") !== "websocket") return new Response("expected a WebSocket", { status: 426 });
  if (!isTopic(topic)) return new Response("bad topic", { status: 400 });
  if (!env.HUB) return new Response("direct link not configured", { status: 503 });
  const hub = env.HUB.get(env.HUB.idFromName("hub"));
  return hub.fetch(new Request(`https://hub/listen?topic=${topic}`, request));
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/listen") return handleListen(request, env);
    if (!pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      return await handleApi(request, env);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message, ...e.extra }, e.status);
      console.error(e);
      return json({ error: "internal error" }, 500);
    }
  },
};

export { HttpError };
