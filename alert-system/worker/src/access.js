// Verifies the Cloudflare Access login token (Zero Trust free plan) on every API call,
// so the Worker refuses to send even if someone reaches it without going through Access.

let jwksCache = null; // { url, keys, fetchedAt }

export function teamOrigin(domain) {
  let d = String(domain || "").trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (d && !d.includes(".")) d += ".cloudflareaccess.com";
  return d ? `https://${d}` : "";
}

function b64urlDecode(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function getKeys(origin, fetchImpl, forceRefresh) {
  const url = `${origin}/cdn-cgi/access/certs`;
  const fresh = jwksCache && jwksCache.url === url && Date.now() - jwksCache.fetchedAt < 3600_000;
  if (fresh && !forceRefresh) return jwksCache.keys;
  const res = await fetchImpl(url);
  if (!res.ok) throw new Error(`could not load Access keys (${res.status})`);
  const keys = (await res.json()).keys || [];
  jwksCache = { url, keys, fetchedAt: Date.now() };
  return keys;
}

// Returns the signed-in email, or throws.
export async function verifyAccessJwt(token, { teamDomain, aud }, fetchImpl = fetch) {
  if (!token) throw new Error("not signed in through Cloudflare Access");
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("malformed Access token");
  const header = JSON.parse(new TextDecoder().decode(b64urlDecode(parts[0])));
  const payload = JSON.parse(new TextDecoder().decode(b64urlDecode(parts[1])));
  if (header.alg !== "RS256") throw new Error("unexpected Access token algorithm");

  const origin = teamOrigin(teamDomain);
  let jwk = (await getKeys(origin, fetchImpl, false)).find((k) => k.kid === header.kid);
  if (!jwk) jwk = (await getKeys(origin, fetchImpl, true)).find((k) => k.kid === header.kid); // key rotation
  if (!jwk) throw new Error("Access token signed by an unknown key");

  const key = await crypto.subtle.importKey(
    "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"],
  );
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", key, b64urlDecode(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
  );
  if (!ok) throw new Error("Access token signature is invalid");

  const now = Math.floor(Date.now() / 1000);
  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(aud)) throw new Error("Access token is for a different application");
  if (payload.iss !== origin) throw new Error("Access token is from a different team");
  if (typeof payload.exp !== "number" || payload.exp < now) throw new Error("Access login expired, reload the page");
  if (typeof payload.nbf === "number" && payload.nbf > now + 60) throw new Error("Access token not yet valid");
  return payload.email || payload.common_name || "unknown";
}

export function _resetJwksCache() {
  jwksCache = null;
}
