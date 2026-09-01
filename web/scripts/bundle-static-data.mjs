// Post-build step for `npm run build:static`: drop the screened-events
// fixture into the built bundle at dist/data/conjunctions.json.
//
// It goes into dist/ (after `vite build`), NOT public/, on purpose: anything
// in public/ is copied into every build, which would make a plain
// `npm run build` also look like a static export. Writing it here means only
// `build:static` produces the file, and the client's runtime probe
// (fetch /data/conjunctions.json) distinguishes the two — one code build,
// both modes.

import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../contracts/fixtures/conjunctions.real.json");
const destDir = resolve(here, "../dist/data");
const dest = resolve(destDir, "conjunctions.json");

mkdirSync(destDir, { recursive: true });
copyFileSync(src, dest);
console.log(`build:static — bundled ${src} -> ${dest}`);
