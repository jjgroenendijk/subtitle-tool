// Refresh the vendored Alpine.js static asset from the pinned npm package.
//
// This is the documented, reproducible step the issue and AGENTS.md refer to:
// after `npm ci` (which installs the version pinned in package-lock.json), run
// `npm run vendor` to copy the matching minified CSP build into the served
// static tree. It is a vendor-refresh helper only, never part of running or
// building the application; the container ships the committed copy.

import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const here = import.meta.dirname;
const version = JSON.parse(
  readFileSync(join(here, "node_modules/@alpinejs/csp/package.json"), "utf8"),
).version;

const source = join(here, "node_modules/@alpinejs/csp/dist/cdn.min.js");
const destDir = join(here, "../src/subtitle_tool/web/static/vendor");
const dest = join(destDir, "alpine.csp.min.js");

mkdirSync(destDir, { recursive: true });
copyFileSync(source, dest);
console.log(`[INFO] vendored @alpinejs/csp ${version} -> ${dest}`);
