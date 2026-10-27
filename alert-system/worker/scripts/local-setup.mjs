// Writes .dev.vars for running the sender site on your own computer.
// Usage: npm run setup-local -- path/to/service-account.json
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

const devVars = fileURLToPath(new URL("../.dev.vars", import.meta.url));
const path = process.argv[2];
if (!path) {
  console.error("Usage: npm run setup-local -- path/to/service-account.json");
  process.exit(1);
}

const sa = JSON.parse(readFileSync(path, "utf8"));
if (!sa.client_email || !sa.private_key || !sa.project_id) {
  console.error(`${path} is not a Firebase service-account key (needs client_email, private_key, project_id).`);
  process.exit(1);
}
const compact = JSON.stringify(sa);
if (compact.includes("'")) {
  console.error("Unexpected ' in the service-account file.");
  process.exit(1);
}

// Keep an existing CODE_SECRET: changing it changes every phone's code.
let secret = randomBytes(24).toString("base64url");
if (existsSync(devVars)) {
  const m = readFileSync(devVars, "utf8").match(/^CODE_SECRET=(.+)$/m);
  if (m) secret = m[1].trim();
}

// Single quotes keep the private key's \n escapes intact for JSON.parse.
writeFileSync(devVars, `DEV_NO_AUTH=true\nCODE_SECRET=${secret}\nFCM_SERVICE_ACCOUNT='${compact}'\n`, { mode: 0o600 });
console.log(`Wrote .dev.vars for Firebase project "${sa.project_id}".`);
console.log(`CODE_SECRET=${secret}`);
console.log("Use this same CODE_SECRET when you deploy to Cloudflare, or every phone will need a new code.");
console.log("Next: npm run dev   (then open http://localhost:8787)");
