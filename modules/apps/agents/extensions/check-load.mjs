import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { pathToFileURL } from "node:url";

// Use the pinned host's loader without a session, model request, or interactive UI.
const [bundle, piRoot] = process.argv.slice(2);
assert.ok(bundle && piRoot, "Usage: node check-load.mjs BUNDLE PI_PACKAGE_ROOT");
const manifest = JSON.parse(readFileSync(`${bundle}/package.json`, "utf8"));
assert.deepEqual(manifest.dependencies, {
  "@juicesharp/rpiv-ask-user-question": "2.15.0",
  "pi-web-access": "0.36.0",
  "pi-btw": "0.8.1",
});
const lock = JSON.parse(readFileSync(`${bundle}/package-lock.json`, "utf8"));
const expectedPackages = Object.keys(lock.packages)
  .filter((path) => path.startsWith("node_modules/"));
function installedPackages(root, prefix = "node_modules") {
  const names = readdirSync(root).filter((name) => !name.startsWith(".")).flatMap((name) =>
    name.startsWith("@")
      ? readdirSync(`${root}/${name}`).map((child) => `${name}/${child}`)
      : [name]);
  return names.flatMap((name) => [
    `${prefix}/${name}`,
    ...(existsSync(`${root}/${name}/node_modules`)
      ? installedPackages(`${root}/${name}/node_modules`, `${prefix}/${name}/node_modules`)
      : []),
  ]);
}
assert.deepEqual(installedPackages(`${bundle}/node_modules`).sort(), expectedPackages.sort(),
  "Installed dependencies must match the lockfile");
for (const name of ["@earendil-works", "typebox", "pi-lens", "pi-split-view",
  "@juicesharp/rpiv-todo", "@narumitw/pi-usage"]) {
  assert.ok(!existsSync(`${bundle}/node_modules/${name}`), `Must not bundle ${name}`);
}
for (const path of ["roles", "agents", "subagent", "checks"]) {
  assert.ok(!existsSync(`${bundle}/${path}`), `Obsolete resource must not ship: ${path}`);
}
assert.ok(existsSync(`${bundle}/node_modules/pi-btw/skills/btw/SKILL.md`));
const { loadExtensions } = await import(
  pathToFileURL(`${piRoot}/dist/core/extensions/loader.js`).href
);
const loaded = await loadExtensions([
  `${bundle}/node_modules/@juicesharp/rpiv-ask-user-question/index.ts`,
  `${bundle}/node_modules/pi-web-access/dist/index.js`,
  `${bundle}/node_modules/pi-btw/extensions/btw.ts`,
], process.cwd());
assert.deepEqual(loaded.errors, [], "All three extensions must load against the pinned Pi host");
assert.equal(loaded.extensions.length, 3);
const [questions, web, btw] = loaded.extensions;
assert.deepEqual([...questions.tools.keys()], ["ask_user_question"]);
// Upstream questions registers one availability reconciler, not a supervisor policy.
assert.equal(questions.handlers.get("before_agent_start")?.length ?? 0, 1);
assert.ok(web.commands.has("websearch"));
assert.ok(web.tools.has("web_search") || web.tools.has("web_enable"),
  "Web access must register search or its lazy-loading entry point");
for (const command of ["btw", "side", "btw:ask", "btw:tangent", "btw:clear"]) {
  assert.ok(btw.commands.has(command), `Missing BTW command: ${command}`);
}
for (const collection of ["tools", "commands", "flags", "shortcuts"]) {
  const names = loaded.extensions.flatMap((extension) => [...extension[collection].keys()]);
  assert.equal(names.length, new Set(names).size, `${collection} must not collide`);
}
const tools = new Set(loaded.extensions.flatMap((extension) => [...extension.tools.keys()]));
for (const name of ["todo", "subagent", "lens_diagnostics"]) {
  assert.ok(!tools.has(name), `Removed tool must not register: ${name}`);
}
for (const extension of loaded.extensions) {
  for (const command of ["usage", "fast", "split", "split-save"]) {
    assert.ok(!extension.commands.has(command), `Removed command must not register: ${command}`);
  }
}
console.log("Questions, web access, and BTW dependency graph and registrations checked");
