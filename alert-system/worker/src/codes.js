// Pairing codes. No database: a phone's code is HMAC(CODE_SECRET, name), so only this
// server can mint a valid one, and the phone listens on a push topic derived from it.
// The Android app (Codes.kt) implements normalizeCode / isValidCode / topicForCode
// identically; test/codes.test.js and CodesTest.kt pin the same vector.

export const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"; // Crockford base32: no I, L, O, U
const enc = new TextEncoder();

export function normalizeName(name) {
  return String(name ?? "").trim().replace(/\s+/g, " ").toLowerCase();
}

export function normalizeCode(code) {
  return String(code ?? "")
    .toUpperCase()
    .replace(/[^0-9A-Z]/g, "")
    .replace(/O/g, "0")
    .replace(/[IL]/g, "1");
}

export function formatCode(code) {
  return normalizeCode(code).match(/.{1,4}/g).join("-");
}

function base32(bytes, length) {
  let out = "";
  let buf = 0;
  let bits = 0;
  let i = 0;
  while (out.length < length) {
    if (bits < 5) {
      buf = (buf << 8) | bytes[i++];
      bits += 8;
    }
    out += ALPHABET[(buf >> (bits - 5)) & 31];
    bits -= 5;
    buf &= (1 << bits) - 1;
  }
  return out;
}

async function sha256(text) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(text)));
}

async function checkChar(body) {
  return ALPHABET[(await sha256("edith-check-v1:" + body))[0] >> 3];
}

export async function codeForName(secret, name) {
  const n = normalizeName(name);
  if (!n) throw new Error("name is empty");
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode("edith-phone-v1:" + n)));
  const body = base32(mac, 15);
  return body + (await checkChar(body));
}

export async function isValidCode(code) {
  const c = normalizeCode(code);
  if (c.length !== 16 || [...c].some((ch) => !ALPHABET.includes(ch))) return false;
  return (await checkChar(c.slice(0, 15))) === c[15];
}

export async function topicForCode(code) {
  const digest = await sha256("edith-topic-v1:" + normalizeCode(code));
  return "edith-" + [...digest].map((b) => b.toString(16).padStart(2, "0")).join("");
}
