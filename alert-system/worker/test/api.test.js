import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { handleApi, handleListen, HttpError } from "../src/index.js";
import { codeForName, topicForCode } from "../src/codes.js";
import { _resetTokenCache } from "../src/fcm.js";
import { rsaKeyPair, pkcs8Pem } from "./helpers.js";

const { privateKey } = await rsaKeyPair();
const SA = JSON.stringify({ project_id: "proj", client_email: "svc@proj.iam.gserviceaccount.com", private_key: await pkcs8Pem(privateKey) });
const env = { DEV_NO_AUTH: "true", CODE_SECRET: "test-secret-please-change", FCM_SERVICE_ACCOUNT: SA };

function mockGoogle(failTopics = []) {
  const sends = [];
  const fetchImpl = async (url, init) => {
    if (url === "https://oauth2.googleapis.com/token") {
      assert.match(String(init.body), /grant_type=urn/);
      return new Response(JSON.stringify({ access_token: "tok", expires_in: 3600 }));
    }
    assert.equal(url, "https://fcm.googleapis.com/v1/projects/proj/messages:send");
    assert.equal(init.headers.authorization, "Bearer tok");
    const msg = JSON.parse(init.body).message;
    sends.push(msg);
    return failTopics.includes(msg.topic) ? new Response("nope", { status: 404 }) : new Response("{}");
  };
  return { sends, fetchImpl };
}

const post = (path, body, headers = {}) => new Request(`https://edith.example.workers.dev${path}`, {
  method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body),
});

beforeEach(() => _resetTokenCache());

test("code endpoint returns the HMAC code", async () => {
  const res = await handleApi(post("/api/code", { name: " Sara " }), env);
  const body = await res.json();
  assert.equal(body.name, "Sara");
  assert.equal(body.code.replace(/-/g, ""), await codeForName(env.CODE_SECRET, "sara"));
});

test("send pushes a high-priority data message to each phone's topic", async () => {
  const { sends, fetchImpl } = mockGoogle();
  const res = await handleApi(post("/api/send", { names: ["Sara", "sara", "Ali"], message: "Fire drill" }), env, fetchImpl);
  const body = await res.json();
  assert.equal(res.status, 200);
  assert.deepEqual(body, { sent: ["Sara", "Ali"], failed: [], online: [] });
  assert.equal(sends.length, 2);
  const saraTopic = await topicForCode(await codeForName(env.CODE_SECRET, "Sara"));
  const sara = sends.find((m) => m.topic === saraTopic); // sends run in parallel, order varies
  assert.ok(sara);
  assert.equal(sara.android.priority, "HIGH");
  assert.equal(sara.data.type, "alert");
  assert.equal(sara.data.message, "Fire drill");
  assert.equal(sara.data.sender, "dev@localhost");
  for (const k of Object.keys(sara.data)) {
    assert.ok(!["from", "notification", "message_type"].includes(k) && !/^(google|gcm)/.test(k), `FCM-reserved key: ${k}`);
  }
  assert.ok(Object.values(sara.data).every((v) => typeof v === "string"));
});

test("stop messages and partial failures", async () => {
  const bad = await topicForCode(await codeForName(env.CODE_SECRET, "Ali"));
  const { sends, fetchImpl } = mockGoogle([bad]);
  const res = await handleApi(post("/api/send", { type: "stop", names: ["Sara", "Ali"] }), env, fetchImpl);
  const body = await res.json();
  assert.deepEqual(body.sent, ["Sara"]);
  assert.equal(body.failed[0].name, "Ali");
  assert.ok(sends.every((m) => m.data.type === "stop"));
});

test("refuses to run with no sender protection configured", async () => {
  await assert.rejects(handleApi(post("/api/code", { name: "x" }), { CODE_SECRET: env.CODE_SECRET }),
    (e) => e instanceof HttpError && e.status === 500 && /SEND_PASSWORD/.test(e.message));
  await assert.rejects(handleApi(post("/api/code", { name: "x" }), { ...env, DEV_NO_AUTH: undefined, ACCESS_TEAM_DOMAIN: "t", ACCESS_AUD: "a" }),
    (e) => e.status === 401);
});

test("input validation and cross-site protection", async () => {
  const bad = async (req, status) => assert.rejects(handleApi(req, env, mockGoogle().fetchImpl), (e) => e.status === status);
  await bad(post("/api/send", { names: [] }), 400);
  await bad(post("/api/send", { names: ["a"], message: "x".repeat(201) }), 400);
  await bad(post("/api/send", { names: Array.from({ length: 51 }, (_, i) => `p${i}`) }), 400);
  await bad(post("/api/send", { names: ["a"] }, { origin: "https://evil.example" }), 403);
  await bad(new Request("https://edith.example.workers.dev/api/send", { method: "POST", body: "names=a" }), 415);
  await assert.rejects(handleApi(post("/api/code", { name: "x" }), { ...env, CODE_SECRET: "short" }), (e) => e.status === 500);
});

test("shared sender password", async () => {
  const pwEnv = { ...env, DEV_NO_AUTH: undefined, SEND_PASSWORD: "correct horse battery" };
  const me = (h) => handleApi(new Request("https://edith.example.workers.dev/api/me", { headers: h }), pwEnv);
  await assert.rejects(me({}), (e) => e.status === 401 && e.extra.auth === "password" && /needed/.test(e.message));
  await assert.rejects(me({ "x-edith-password": "correct horse batterY" }), (e) => e.status === 401 && /wrong/.test(e.message));
  const ok = await (await me({ "x-edith-password": "correct horse battery", "x-edith-sender": "  Mohammed  " })).json();
  assert.deepEqual(ok, { email: "Mohammed", auth: "password" });

  const { sends, fetchImpl } = mockGoogle();
  await handleApi(post("/api/send", { names: ["Sara"] }, { "x-edith-password": "correct horse battery" }), pwEnv, fetchImpl);
  assert.equal(sends[0].data.sender, "Sender");

  await assert.rejects(handleApi(new Request("https://e.workers.dev/api/me", { headers: { "x-edith-password": "abc" } }), { ...pwEnv, SEND_PASSWORD: "abc" }),
    (e) => e.status === 500 && /at least 8/.test(e.message));
});

test("Cloudflare Access takes priority over the password", async () => {
  const both = { ...env, DEV_NO_AUTH: undefined, SEND_PASSWORD: "correct horse battery", ACCESS_TEAM_DOMAIN: "t", ACCESS_AUD: "a" };
  await assert.rejects(handleApi(new Request("https://e.workers.dev/api/me", { headers: { "x-edith-password": "correct horse battery" } }), both),
    (e) => e.status === 401 && !e.extra.auth);
});

function mockHub(connectedTopics) {
  const calls = [];
  return {
    calls,
    idFromName: (n) => n,
    get: () => ({
      fetch: async (url, init) => {
        if (typeof url === "string" && url.endsWith("/broadcast")) {
          const { topics, data } = JSON.parse(init.body);
          calls.push({ topics, data });
          return Response.json(Object.fromEntries(topics.map((t) => [t, connectedTopics.includes(t) ? 1 : 0])));
        }
        calls.push({ listen: url.url ?? url });
        return new Response("upgraded");
      },
    }),
  };
}

test("alerts go down the direct link too, and a connected phone counts as sent even if Google fails", async () => {
  const sara = await topicForCode(await codeForName(env.CODE_SECRET, "Sara"));
  const ali = await topicForCode(await codeForName(env.CODE_SECRET, "Ali"));
  const HUB = mockHub([sara]);
  const { fetchImpl } = mockGoogle([sara, ali]); // Google fails for both
  const res = await handleApi(post("/api/send", { names: ["Sara", "Ali"], message: "Up" }), { ...env, HUB }, fetchImpl);
  const body = await res.json();
  assert.deepEqual(body.sent, ["Sara"]);
  assert.deepEqual(body.online, ["Sara"]);
  assert.equal(body.failed[0].name, "Ali");
  assert.deepEqual(HUB.calls[0].topics, [sara, ali]);
  assert.equal(HUB.calls[0].data.message, "Up");
});

test("listen endpoint validates before handing the socket to the hub", async () => {
  const HUB = mockHub([]);
  const topic = await topicForCode(await codeForName(env.CODE_SECRET, "Sara"));
  const ws = (q, h = { upgrade: "websocket" }) => handleListen(new Request(`https://e.workers.dev/api/listen?${q}`, { headers: h }), { HUB });
  assert.equal((await ws(`topic=${topic}`, {})).status, 426);
  assert.equal((await ws("topic=edith-nothex")).status, 400);
  assert.equal((await handleListen(new Request(`https://e/api/listen?topic=${topic}`, { headers: { upgrade: "websocket" } }), {})).status, 503);
  assert.equal(await (await ws(`topic=${topic}`)).text(), "upgraded");
  assert.match(HUB.calls[0].listen, new RegExp(`/listen\\?topic=${topic}$`));
});
