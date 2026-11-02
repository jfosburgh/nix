import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Exercise the pinned host's loader without a session, model request, or LSP startup.
const [bundle, piRoot] = process.argv.slice(2);
assert.ok(bundle && piRoot, "Usage: node check-load.mjs BUNDLE PI_PACKAGE_ROOT");
const { loadExtensions } = await import(
  pathToFileURL(`${piRoot}/dist/core/extensions/loader.js`).href
);
const paths = [
  `${bundle}/node_modules/@juicesharp/rpiv-ask-user-question/index.ts`,
  `${bundle}/node_modules/@juicesharp/rpiv-todo/index.ts`,
  `${bundle}/node_modules/pi-lens/dist/index.js`,
  `${bundle}/subagent/index.ts`,
  `${bundle}/node_modules/@narumitw/pi-usage/dist/index.ts`,
  `${bundle}/node_modules/pi-split-view/split-view.ts`,
];
const main = await loadExtensions(paths, process.cwd());
assert.deepEqual(main.errors, [], "Every extension must load against the pinned Pi host");
assert.equal(main.extensions.length, paths.length);
const tools = new Set(main.extensions.flatMap((extension) => [...extension.tools.keys()]));
for (const tool of ["ask_user_question", "todo", "lens_diagnostics", "subagent"]) {
  assert.ok(tools.has(tool), `Expected registered tool: ${tool}`);
}

// Provider usage and split-view are main-agent UI: no worker may inherit them.
const mainOnlyCommands = [
  "usage", "fast",
  "split", "split-thinking", "split-tools", "files", "split-diff",
  "split-tools-view", "split-height", "split-tools-width", "split-divider",
  "split-trim-response", "split-save",
];

// Exercise the actual worker entry point; dispatch isolation is tested separately.
const worker = await loadExtensions([`${bundle}/roles/worker.ts`], process.cwd());
assert.deepEqual(worker.errors, []);
assert.equal(worker.extensions.length, 1);
assert.ok(worker.extensions[0].tools.has("lens_diagnostics"));
for (const tool of ["ask_user_question", "todo", "subagent"]) {
  assert.ok(!worker.extensions[0].tools.has(tool), `Worker must not register ${tool}`);
}
for (const name of mainOnlyCommands) {
  assert.ok(!worker.extensions[0].commands.has(name), `Worker must not register /${name}`);
}
assert.ok(!worker.extensions[0].flags.has("no-split"), "Worker must not register the split-view flag");
console.log("Underlying extensions and Lens-only worker entry point loaded successfully");

const supervisor = await loadExtensions([`${bundle}/roles/main.ts`], process.cwd());
assert.deepEqual(supervisor.errors, []);
assert.equal(supervisor.extensions.length, 1);
const supervisorExtension = supervisor.extensions[0];
for (const collection of ["tools", "commands", "flags", "shortcuts"]) {
  const underlyingNames = main.extensions.flatMap((extension) => [...extension[collection].keys()]);
  const uniqueNames = [...new Set(underlyingNames)];
  assert.equal(underlyingNames.length, uniqueNames.length, `Bundled ${collection} must not collide`);
  assert.deepEqual([...supervisorExtension[collection].keys()].sort(), uniqueNames.sort());
}

for (const name of mainOnlyCommands) {
  assert.ok(supervisorExtension.commands.has(name), `Main agent must register /${name}`);
}
assert.ok(supervisorExtension.flags.has("no-split"), "Main agent must register the split-view flag");

// The policy is registered after package hooks, and changes only its own section.
const supervisorHandlers = supervisorExtension.handlers.get("before_agent_start");
const underlyingHandlerCount = main.extensions.reduce((count, extension) =>
  count + (extension.handlers.get("before_agent_start")?.length ?? 0), 0);
assert.equal(supervisorHandlers.length, underlyingHandlerCount + 1);
const policyHandler = supervisorHandlers.at(-1);
const policy = readFileSync(`${bundle}/roles/supervisor.md`, "utf8").trim();
const { buildSystemPromptSections } = await import(
  pathToFileURL(`${piRoot}/dist/core/system-prompt.js`).href
);
for (const messageType of ["user", "custom"]) {
  for (const customPrompt of [undefined, "Keep the user's custom system prompt."]) {
    const event = {
      messageType,
      systemPromptOptions: {
        cwd: process.cwd(), selectedTools: ["read"], customPrompt,
        sections: { existing: "Keep existing sections." },
        promptGuidelines: ["Keep existing guidelines."],
      },
    };
    assert.equal(await policyHandler(event, {}), undefined);
    const first = structuredClone(event.systemPromptOptions);
    await policyHandler(event, {});
    assert.deepEqual(event.systemPromptOptions, first, "Repeated runs must not duplicate policy");
    assert.deepEqual(event.systemPromptOptions.sections, {
      existing: "Keep existing sections.", development_supervisor: policy,
    });
    assert.deepEqual(event.systemPromptOptions.promptGuidelines, ["Keep existing guidelines."]);
    const sections = buildSystemPromptSections(event.systemPromptOptions);
    assert.equal(sections.development_supervisor, `<development_supervisor>\n${policy}\n</development_supervisor>`);
    if (customPrompt) assert.equal(sections.preamble, customPrompt);
  }
}
assert.equal(worker.extensions[0].handlers.get("before_agent_start")?.length ?? 0,
  main.extensions[2].handlers.get("before_agent_start")?.length ?? 0,
  "Worker must retain Lens hooks without adding the supervisor policy hook");
console.log("Supervisor composition and stable main-only policy section checked");

// A missing/empty policy must not leave an unconstrained, partially loaded main agent.
const fixtureRoot = mkdtempSync(join(tmpdir(), "pi supervisor policy "));
try {
  for (const variant of ["missing", "empty"]) {
    const root = join(fixtureRoot, variant);
    mkdirSync(join(root, "roles"), { recursive: true });
    copyFileSync(`${bundle}/roles/main.ts`, join(root, "roles/main.ts"));
    symlinkSync(`${bundle}/roles/lens.ts`, join(root, "roles/lens.ts"));
    symlinkSync(`${bundle}/node_modules`, join(root, "node_modules"));
    symlinkSync(`${bundle}/subagent`, join(root, "subagent"));
    if (variant === "empty") writeFileSync(join(root, "roles/supervisor.md"), " \n\t\n");
    const rejected = await loadExtensions([join(root, "roles/main.ts")], process.cwd());
    assert.equal(rejected.extensions.length, 0);
    assert.equal(rejected.errors.length, 1);
    if (variant === "empty") {
      assert.equal(rejected.errors[0].error,
        "Failed to load extension: Development supervisor policy is empty; refusing to initialize");
    } else {
      assert.match(rejected.errors[0].error, /ENOENT.*supervisor\.md/);
    }
  }
} finally {
  rmSync(fixtureRoot, { recursive: true, force: true });
}
console.log("Missing/empty supervisor policy rejects initialization without partial registration");
const { parseFrontmatter } = await import(pathToFileURL(`${piRoot}/dist/index.js`).href);
const { frontmatter, body } = parseFrontmatter(
  readFileSync(`${bundle}/agents/coder.md`, "utf8"),
);
assert.equal(frontmatter.name, "coder");
assert.equal(frontmatter.model, "strata-server/strata-coder");
assert.ok(body.trim().length > 0);
console.log("Coder definition selects strata-server/strata-coder");
