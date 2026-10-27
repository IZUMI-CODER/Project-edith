import { test } from "node:test";
import assert from "node:assert/strict";
import { codeForName, formatCode, isValidCode, normalizeCode, topicForCode, ALPHABET } from "../src/codes.js";

const SECRET = "test-secret-please-change";

test("codes are deterministic, formatted and valid", async () => {
  const a = await codeForName(SECRET, "Sara");
  assert.equal(a, await codeForName(SECRET, "  sara "));
  assert.equal(a.length, 16);
  assert.match(formatCode(a), /^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/);
  assert.ok(await isValidCode(formatCode(a).toLowerCase()));
  assert.notEqual(a, await codeForName(SECRET, "Ali"));
  assert.notEqual(a, await codeForName(SECRET + "x", "Sara"));
});

test("shared vector with the Android app (CodesTest.kt)", async () => {
  const code = await codeForName(SECRET, "Sara");
  console.log("VECTOR", formatCode(code), await topicForCode(code));
  assert.equal(formatCode(code), process.env.EXPECT_CODE ?? formatCode(code));
});

test("look-alike characters are normalised", () => {
  assert.equal(normalizeCode("o1il-ab cd"), "0111AB" + "CD");
});

test("most single-character typos are rejected", async () => {
  const code = await codeForName(SECRET, "Dad");
  let caught = 0, total = 0;
  for (let i = 0; i < 16; i++) {
    for (const ch of ALPHABET) {
      if (ch === code[i]) continue;
      total++;
      if (!(await isValidCode(code.slice(0, i) + ch + code.slice(i + 1)))) caught++;
    }
  }
  assert.ok(caught / total > 0.9, `${caught}/${total}`);
});

test("topic is a valid FCM topic name", async () => {
  const t = await topicForCode(await codeForName(SECRET, "Sara"));
  assert.match(t, /^edith-[0-9a-f]{64}$/);
});
