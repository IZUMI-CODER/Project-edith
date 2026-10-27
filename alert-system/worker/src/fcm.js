// Firebase Cloud Messaging (HTTP v1) from a Worker: sign a service-account JWT with
// WebCrypto, swap it for an OAuth token, then send a high-priority data message.

const enc = new TextEncoder();
let cachedToken = null; // { token, expiresAt, email }

export function b64url(input) {
  const bytes = typeof input === "string" ? enc.encode(input) : input;
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function pemToDer(pem) {
  const b64 = pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

export function parseServiceAccount(raw) {
  let sa;
  try {
    sa = JSON.parse(raw);
  } catch {
    throw new Error("FCM_SERVICE_ACCOUNT is not valid JSON");
  }
  if (!sa.client_email || !sa.private_key || !sa.project_id) {
    throw new Error("FCM_SERVICE_ACCOUNT is missing client_email, private_key or project_id");
  }
  return sa;
}

async function getAccessToken(sa, fetchImpl) {
  const now = Math.floor(Date.now() / 1000);
  if (cachedToken && cachedToken.email === sa.client_email && cachedToken.expiresAt > now + 60) {
    return cachedToken.token;
  }
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = b64url(JSON.stringify({
    iss: sa.client_email,
    scope: "https://www.googleapis.com/auth/firebase.messaging",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  }));
  const key = await crypto.subtle.importKey(
    "pkcs8", pemToDer(sa.private_key), { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, enc.encode(`${header}.${claims}`)));
  const res = await fetchImpl("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${header}.${claims}.${b64url(sig)}`,
    }),
  });
  if (!res.ok) throw new Error(`Google token exchange failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  const body = await res.json();
  cachedToken = { token: body.access_token, expiresAt: now + (body.expires_in || 3600), email: sa.client_email };
  return cachedToken.token;
}

export async function sendToTopic(sa, topic, data, fetchImpl = fetch) {
  const token = await getAccessToken(sa, fetchImpl);
  const res = await fetchImpl(`https://fcm.googleapis.com/v1/projects/${sa.project_id}/messages:send`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({
      message: {
        topic,
        data, // data-only, so the app's service runs even when the app is closed
        android: { priority: "HIGH", ttl: "600s" },
      },
    }),
  });
  if (!res.ok) throw new Error(`FCM send failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
}

export function _resetTokenCache() {
  cachedToken = null;
}
