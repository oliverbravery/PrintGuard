import { readFileSync } from "node:fs";
import { lint } from "../src/lint.ts";

const bundle = JSON.parse(readFileSync(process.argv[2], "utf8"));
process.stdout.write(JSON.stringify(lint(bundle.manifest, bundle.sources, bundle.permissions)));
