import { codeForName, formatCode, normalizeName, topicForCode } from "./codes.js";
import { parseServiceAccount, sendToTopic } from "./fcm.js";
import { verifyAccessJwt } from "./access.js";

const MAX_MESSAGE = 200;
const MAX_TARGETS = 50;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function authenticate(request, env, fetchImpl) {
  if (env.DEV_NO_AUTH === "true") return "dev@localhost";
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) {
    throw new HttpError(500, "Cloudflare Access is not configured (ACCESS_TEAM_DOMAIN / ACCESS_AUD). Refusing to run unprotected.");
  }
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
  const results = await Promise.allSettled(names.map(async (name) => {
    const topic = await topicForCode(await codeForName(secret, name));
    await sendToTopic(sa, topic, data, fetchImpl);
  }));
  const sent = [];
  const failed = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") sent.push(names[i]);
    else failed.push({ name: names[i], error: String(r.reason?.message || r.reason) });
  });
  return { sent, failed };
}

export async function handleApi(request, env, fetchImpl = fetch) {
  const { pathname } = new URL(request.url);
  const email = await authenticate(request, env, fetchImpl);

  if (pathname === "/api/me" && request.method === "GET") {
    return json({ email });
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
      from: email,
      sent_at: String(Date.now()),
    };
    const result = await sendAll(env, names, data, fetchImpl);
    console.log(JSON.stringify({ event: type, from: email, sent: result.sent.length, failed: result.failed.length }));
    return json(result, result.sent.length ? 200 : 502);
  }

  throw new HttpError(404, "not found");
}

export default {
  async fetch(request, env) {
    if (!new URL(request.url).pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      return await handleApi(request, env);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status);
      console.error(e);
      return json({ error: "internal error" }, 500);
    }
  },
};

export { HttpError };
