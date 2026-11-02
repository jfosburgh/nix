import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [bundle, piRoot] = process.argv.slice(2);
assert.ok(bundle && piRoot, "Usage: node check-lens.mjs BUNDLE PI_PACKAGE_ROOT");
const { loadExtensions } = await import(
  pathToFileURL(`${piRoot}/dist/core/extensions/loader.js`).href
);

// Use Pi's loader so the real Lens modules resolve host peers exactly as in Pi.
const result = await loadExtensions([`${bundle}/checks/lens-policy.ts`], process.cwd());
assert.deepEqual(result.errors, []);
assert.equal(result.extensions.length, 1);
assert.ok(result.extensions[0].tools.has("lens_diagnostics"));
for (const tool of ["ask_user_question", "todo", "subagent"]) {
  assert.ok(!result.extensions[0].tools.has(tool));
}
console.log("Both Lens resolvers reject mutation overrides; diagnostic initializer loads Lens only");

// Isolate negative fixtures: even policy failure must not run an unsafe factory.
const fixtureRoot = mkdtempSync(join(tmpdir(), "pi-lens-initializer-"));
const requiredFlags = {
  "no-autoformat": true,
  "no-autofix": true,
  "lens-actionable-warning-autofix": false,
};
try {
  for (const variant of [
    "missing-policy",
    ...Object.keys(requiredFlags),
    "wrong-source",
    "import-failure",
    "initialization-failure",
  ]) {
    const root = join(fixtureRoot, variant);
    const roles = join(root, "roles");
    const lens = join(root, "node_modules/pi-lens/dist");
    mkdirSync(roles, { recursive: true });
    mkdirSync(lens, { recursive: true });
    writeFileSync(join(root, "package.json"), '{"type":"module"}\n');
    copyFileSync(`${bundle}/roles/lens.ts`, join(roles, "lens.ts"));
    writeFileSync(join(root, "entry.ts"),
      'export { registerDiagnosticLens as default } from "./roles/lens.ts";\n');

    const values = { ...requiredFlags };
    if (Object.hasOwn(values, variant)) values[variant] = !values[variant];
    const source = variant === "wrong-source" ? "default" : "nix-policy";
    const resolver = variant === "missing-policy" ? "" : `
export function resolveNixLensFlag(name) {
  return { value: ${JSON.stringify(values)}[name], source: ${JSON.stringify(source)} };
}`;
    writeFileSync(join(lens, "index.js"), `
if (process.env.PI_LENS_DISABLE_LSP_INSTALL !== "1" || process.env.PI_LENS_DISABLE_TOOL_INSTALL !== "1") {
  throw new Error("Lens imported before disabling managed installation");
}
${variant === "import-failure" ? 'throw new Error("Lens import fixture failure");' : ""}
${resolver}
export default function () {
  throw new Error("Lens initialization fixture failure");
}
`);

    let expectedError;
    if (variant === "missing-policy") {
      expectedError = "Lens diagnostics-only policy is missing; refusing to initialize";
    } else if (variant === "import-failure") {
      expectedError = "Lens import fixture failure";
    } else if (variant === "initialization-failure") {
      expectedError = "Lens initialization fixture failure";
    } else {
      const flag = variant === "wrong-source" ? "no-autoformat" : variant;
      expectedError = `Lens diagnostics-only policy failed for ${flag}; refusing to initialize`;
    }
    process.env.PI_LENS_DISABLE_LSP_INSTALL = "0";
    process.env.PI_LENS_DISABLE_TOOL_INSTALL = "0";
    const failed = await loadExtensions([join(root, "entry.ts")], process.cwd());
    assert.equal(failed.extensions.length, 0);
    assert.equal(failed.errors.length, 1);
    assert.equal(failed.errors[0].error, `Failed to load extension: ${expectedError}`);
    assert.equal(process.env.PI_LENS_DISABLE_LSP_INSTALL, "1");
    assert.equal(process.env.PI_LENS_DISABLE_TOOL_INSTALL, "1");
  }
} finally {
  rmSync(fixtureRoot, { recursive: true, force: true });
}
console.log("Missing/incorrect policy and Lens initialization failures reject without fallback");
