import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import standaloneCode from "ajv/dist/standalone/index.js";
import { build } from "esbuild";

// Compile only maintainer-owned schemas, at build time; browser CSP never needs unsafe-eval.
const ajv = new Ajv2020({ strict: false, allErrors: false, ownProperties: true, code: { source: true, esm: true } });
for (const [id, name] of [["request", "bridge"], ["handshake", "handshake"]]) {
  const source = new URL(`../../../contracts/src/openform_contracts/schemas/${name}.json`, import.meta.url);
  ajv.addSchema(JSON.parse(await readFile(source, "utf8")), id);
}
const contents = standaloneCode(ajv, { validRequest: "request", validHandshake: "handshake" });
const output = await build({
  stdin: { contents, resolveDir: fileURLToPath(new URL("..", import.meta.url)), sourcefile: "bridge-validators.js" },
  bundle: true, write: false, format: "esm", platform: "browser", target: "es2023",
});
await writeFile(new URL("../runtime/validators.generated.js", import.meta.url), output.outputFiles[0].text);
