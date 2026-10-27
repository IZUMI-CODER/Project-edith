import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { verifyAccessJwt, teamOrigin, _resetJwksCache } from "../src/access.js";
import { rsaKeyPair, signJwt } from "./helpers.js";

const TEAM = "https://myteam.cloudflareaccess.com";
const AUD = "aud-tag-123";
const { privateKey, publicKey } = await rsaKeyPair();
const jwk = { ...(await crypto.subtle.exportKey("jwk", publicKey)), kid: "k1" };
const fetchCerts = async (url) => {
  assert.equal(url, `${TEAM}/cdn-cgi/access/certs`);
  return new Response(JSON.stringify({ keys: [jwk] }));
};
const now = () => Math.floor(Date.now() / 1000);
const token = (over = {}) => signJwt(privateKey, { alg: "RS256", kid: "k1" },
  { aud: [AUD], iss: TEAM, email: "me@example.com", exp: now() + 600, ...over });

beforeEach(() => _resetJwksCache());

test("team domain forms", () => {
  assert.equal(teamOrigin("myteam"), TEAM);
  assert.equal(teamOrigin("myteam.cloudflareaccess.com"), TEAM);
  assert.equal(teamOrigin("https://myteam.cloudflareaccess.com/"), TEAM);
});

test("accepts a valid token", async () => {
  assert.equal(await verifyAccessJwt(await token(), { teamDomain: "myteam", aud: AUD }, fetchCerts), "me@example.com");
});

test("rejects wrong audience, issuer, expiry, tampering and missing token", async () => {
  const cfg = { teamDomain: "myteam", aud: AUD };
  await assert.rejects(verifyAccessJwt(await token({ aud: ["other"] }), cfg, fetchCerts), /different application/);
  await assert.rejects(verifyAccessJwt(await token({ iss: "https://evil.cloudflareaccess.com" }), cfg, fetchCerts), /different team/);
  await assert.rejects(verifyAccessJwt(await token({ exp: now() - 5 }), cfg, fetchCerts), /expired/);
  const t = (await token()).split(".");
  const forged = Buffer.from(JSON.stringify({ aud: [AUD], iss: TEAM, email: "x@evil", exp: now() + 600 })).toString("base64url");
  await assert.rejects(verifyAccessJwt(`${t[0]}.${forged}.${t[2]}`, cfg, fetchCerts), /signature/);
  await assert.rejects(verifyAccessJwt(null, cfg, fetchCerts), /not signed in/);
});

test("rejects a token from an unknown key", async () => {
  const other = await rsaKeyPair();
  const t = await signJwt(other.privateKey, { alg: "RS256", kid: "k2" }, { aud: [AUD], iss: TEAM, exp: now() + 600 });
  await assert.rejects(verifyAccessJwt(t, { teamDomain: "myteam", aud: AUD }, fetchCerts), /unknown key/);
});
