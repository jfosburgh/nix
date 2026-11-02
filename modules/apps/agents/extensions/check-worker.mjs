import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [bundle, piRoot] = process.argv.slice(2);
assert.ok(bundle && piRoot, "Usage: node check-worker.mjs BUNDLE PI_PACKAGE_ROOT");
const { loadExtensions } = await import(
  pathToFileURL(`${piRoot}/dist/core/extensions/loader.js`).href
);
const { DefaultResourceLoader, SettingsManager } = await import(
  pathToFileURL(`${piRoot}/dist/index.js`).href
);
const root = mkdtempSync(join(tmpdir(), "pi worker isolation "));
const project = join(root, "project with spaces");
const agentDir = join(root, "user-agent");
const localPackage = join(root, "local-package");
const recordPath = join(root, "child-records.jsonl");
const expectedLensSkills = [
  "pi-lens-ast-grep", "pi-lens-lsp-navigation",
  "pi-lens-write-ast-grep-rule", "pi-lens-write-tree-sitter-rule",
];
// Main-agent UI commands the managed re-export must expose and the worker must not.
const mainOnlyCommands = [
  "usage", "fast",
  "split", "split-thinking", "split-tools", "files", "split-diff",
  "split-tools-view", "split-height", "split-tools-width", "split-divider",
  "split-trim-response", "split-save",
];
const oldScript = process.argv[1];
const environmentNames = [
  "PI_CODING_AGENT_DIR", "PI_TEST_PI_ROOT", "PI_TEST_RECORD", "PI_TEST_CHILD_EXIT",
  "PI_LENS_DISABLE_LSP_INSTALL", "PI_LENS_DISABLE_TOOL_INSTALL",
];
const oldEnvironment = new Map(environmentNames.map((name) => [name, process.env[name]]));
try {
  for (const [directory, name] of [
    [agentDir, "user"], [join(project, ".pi"), "project"], [localPackage, "package"],
  ]) {
    mkdirSync(join(directory, "extensions"), { recursive: true });
    mkdirSync(join(directory, "skills", `fixture-${name}`), { recursive: true });
    mkdirSync(join(directory, "prompts"), { recursive: true });
    writeFileSync(join(directory, "extensions", "fixture.ts"), `
export default function (pi) {
  pi.registerTool({
    name: "fixture_${name}", label: "Fixture", description: "Isolation fixture",
    parameters: { type: "object", properties: {} },
    async execute() { return { content: [], details: undefined }; }
  });
}
`);
    writeFileSync(join(directory, "skills", `fixture-${name}`, "SKILL.md"),
      `---\nname: fixture-${name}\ndescription: Isolation fixture\n---\nFixture skill.\n`);
    writeFileSync(join(directory, "prompts", `fixture-${name}.md`), "Fixture prompt.\n");
  }
  writeFileSync(join(localPackage, "package.json"), '{"name":"worker-isolation-fixture"}\n');
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({
    packages: [localPackage], defaultProvider: "fixture", defaultModel: "keep-local-model",
  }));
  const settingsBefore = readFileSync(join(agentDir, "settings.json"), "utf8");
  // Mirror Home Manager's re-export and symlinks, rather than loading the main role directly.
  writeFileSync(join(agentDir, "extensions/development.ts"),
    `export { default } from "${bundle}/roles/main.ts";\n`);
  symlinkSync(`${bundle}/node_modules/pi-lens/skills`, join(agentDir, "skills/pi-lens"));
  writeFileSync(join(project, ".pi/settings.json"), "{}\n");
  writeFileSync(join(agentDir, "AGENTS.md"), "User instruction fixture.\n");
  writeFileSync(join(project, "AGENTS.md"), "Project instruction fixture.\n");
  mkdirSync(join(agentDir, "agents"));
  symlinkSync(`${bundle}/agents/coder.md`, join(agentDir, "agents/coder.md"));
  mkdirSync(join(project, ".pi/agents"));
  writeFileSync(join(project, ".pi/agents/coder.md"),
    "---\nname: coder\ndescription: Unselected project agent\nmodel: openai/not-approved\n---\nWrong worker.\n");

  process.env.PI_CODING_AGENT_DIR = agentDir;
  process.env.PI_TEST_PI_ROOT = piRoot;
  process.env.PI_TEST_RECORD = recordPath;
  process.env.PI_LENS_DISABLE_LSP_INSTALL = "0";
  process.env.PI_LENS_DISABLE_TOOL_INSTALL = "0";
  delete process.env.PI_TEST_CHILD_EXIT;

  // Prove the trusted-project fixtures are discoverable without isolation flags.
  const settingsManager = SettingsManager.create(project, agentDir);
  settingsManager.setProjectTrusted(true);
  const baseline = new DefaultResourceLoader({ cwd: project, agentDir, settingsManager });
  await baseline.reload();
  assert.deepEqual(baseline.getExtensions().errors, []);
  const baselineTools = baseline.getExtensions().extensions.flatMap((extension) => [...extension.tools.keys()]);
  const baselineCommands = baseline.getExtensions().extensions.flatMap((extension) => [...extension.commands.keys()]);
  for (const tool of ["ask_user_question", "todo", "lens_diagnostics", "subagent"]) {
    assert.ok(baselineTools.includes(tool), `Managed main entry point must register ${tool}`);
  }
  for (const name of mainOnlyCommands) {
    assert.ok(baselineCommands.includes(name), `Managed main entry point must register /${name}`);
  }
  for (const name of expectedLensSkills) {
    assert.ok(baseline.getSkills().skills.some((skill) => skill.name === name));
  }
  assert.equal(settingsManager.getDefaultProvider(), "fixture");
  assert.equal(settingsManager.getDefaultModel(), "keep-local-model");
  assert.equal(readFileSync(join(agentDir, "settings.json"), "utf8"), settingsBefore);
  for (const name of ["user", "project", "package"]) {
    assert.ok(baselineTools.includes(`fixture_${name}`));
    assert.ok(baseline.getSkills().skills.some((skill) => skill.name === `fixture-${name}`));
    assert.ok(baseline.getPrompts().prompts.some((prompt) => prompt.name === `fixture-${name}`));
  }

  const loaded = await loadExtensions([`${bundle}/subagent/index.ts`], project);
  assert.deepEqual(loaded.errors, []);
  const tool = loaded.extensions[0].tools.get("subagent").definition;
  const context = {
    cwd: project, hasUI: false,
    model: { provider: "openai", id: "gpt-6.1-sol" }, thinkingLevel: "high",
  };
  // Upstream invokes the current script with Node. Substitute only the child
  // script, retaining its real spawn, argument construction and JSON handling.
  process.argv[1] = `${bundle}/checks/worker-child.mjs`;
  const task = "Implement only the approved step.\nPreserve spaces and this newline.";
  const alternateCwd = join(project, "alternate cwd");
  mkdirSync(alternateCwd);
  for (const fail of [false, true]) {
    process.env.PI_TEST_CHILD_EXIT = fail ? "7" : "0";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30_000);
    try {
      const result = await tool.execute("worker-test", {
        agent: "coder", task, ...(fail ? { cwd: alternateCwd } : {}),
      }, controller.signal, undefined, context);
      assert.equal(Boolean(result.isError), fail);
      assert.equal(result.details.results[0].exitCode, fail ? 7 : 0);
      assert.equal(result.details.results[0].model, "strata-server/strata-coder");
      assert.equal(result.details.results[0].agentSource, "user");
      assert.match(result.content[0].text, fail ? /Fixture worker unavailable/ : /Fixture worker completed/);
    } finally {
      clearTimeout(timeout);
    }
  }

  const unknown = await tool.execute("unknown-worker-test", {
    agent: "not-defined", task,
  }, undefined, undefined, context);
  assert.equal(unknown.isError, true);
  assert.match(unknown.content[0].text, /Unknown agent/);

  const records = readFileSync(recordPath, "utf8").trim().split("\n").map((line) => JSON.parse(line));
  assert.equal(records.length, 2, "No retry, model fallback or spawn for unknown agents");
  for (const [index, record] of records.entries()) {
    assert.equal(record.cwd, index === 0 ? project : alternateCwd);
    assert.equal(record.args.mode, "json");
    assert.equal(record.args.print, true);
    assert.equal(record.args.noSession, true);
    assert.equal(record.args.model, "strata-server/strata-coder");
    assert.equal(record.args.thinking, undefined, "Do not inherit Sol's thinking setting for an explicitly selected worker model");
    assert.equal(record.args.noExtensions, true);
    assert.equal(record.args.noSkills, true);
    assert.equal(record.args.noPromptTemplates, true);
    assert.notEqual(record.args.noContextFiles, true);
    assert.deepEqual(record.args.extensions, [`${bundle}/roles/worker.ts`]);
    assert.deepEqual(record.args.skills, [`${bundle}/node_modules/pi-lens/skills`]);
    assert.deepEqual(record.args.messages, [`Task: ${task}`]);
    assert.equal(record.promptContents.length, 1);
    assert.match(record.promptContents[0], /# Coding worker/);
    assert.doesNotMatch(record.promptContents[0], /# Development supervisor/);
    for (const path of record.promptPaths) assert.ok(!existsSync(path), "Temporary worker prompt must be removed");
  }
  const worker = records[0];
  assert.deepEqual(worker.extensionPaths, [`${bundle}/roles/worker.ts`]);
  assert.ok(worker.tools.includes("lens_diagnostics"));
  for (const name of ["ask_user_question", "todo", "subagent", "fixture_user", "fixture_project", "fixture_package"]) {
    assert.ok(!worker.tools.includes(name));
  }
  for (const name of mainOnlyCommands) {
    assert.ok(!worker.commands.includes(name), "Spawned worker must not expose /" + name);
  }
  assert.ok(!worker.flags.includes("no-split"), "Spawned worker must not expose the split-view flag");
  assert.deepEqual(worker.skills, expectedLensSkills);
  assert.deepEqual(worker.prompts, []);
  assert.ok(worker.contextPaths.includes(join(agentDir, "AGENTS.md")));
  assert.ok(worker.contextPaths.includes(join(project, "AGENTS.md")));
  assert.deepEqual(worker.appendedInstructions, worker.promptContents);
  assert.deepEqual(worker.downloadControls, ["1", "1"]);
  console.log("Managed main re-export, coder/skill symlinks and local settings/package preservation checked");
  console.log("Spawned worker fixture preserves model/context and isolates extensions, skills and prompts");
  console.log("Failure propagation, user agent scope and temporary-prompt cleanup checked without a model request");
} finally {
  process.argv[1] = oldScript;
  for (const [name, value] of oldEnvironment) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
  rmSync(root, { recursive: true, force: true });
}
