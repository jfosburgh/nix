// Fixture child: exercise Pi's argument parser and resource loader, never a model/session.
import assert from "node:assert/strict";
import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const piRoot = process.env.PI_TEST_PI_ROOT;
const { parseArgs } = await import(pathToFileURL(`${piRoot}/dist/cli/args.js`).href);
const { DefaultResourceLoader, SettingsManager } = await import(
  pathToFileURL(`${piRoot}/dist/index.js`).href
);
const args = parseArgs(process.argv.slice(2));
assert.deepEqual(args.diagnostics, []);
assert.equal(args.unknownFlags.size, 0);
const record = {
  cwd: process.cwd(),
  args,
  promptPaths: args.appendSystemPrompt,
  promptContents: args.appendSystemPrompt.map((path) => readFileSync(path, "utf8")),
};
if (process.env.PI_TEST_CHILD_EXIT === "7") {
  appendFileSync(process.env.PI_TEST_RECORD, JSON.stringify(record) + "\n");
  console.error("Fixture worker unavailable");
  process.exit(7);
}

const settingsManager = SettingsManager.create(process.cwd(), process.env.PI_CODING_AGENT_DIR);
// Trust the fixture project so exclusion cannot pass merely because it was untrusted.
settingsManager.setProjectTrusted(true);
const resources = new DefaultResourceLoader({
  cwd: process.cwd(),
  agentDir: process.env.PI_CODING_AGENT_DIR,
  settingsManager,
  noExtensions: args.noExtensions,
  noSkills: args.noSkills,
  noPromptTemplates: args.noPromptTemplates,
  noContextFiles: args.noContextFiles,
  additionalExtensionPaths: args.extensions,
  additionalSkillPaths: args.skills,
  appendSystemPrompt: args.appendSystemPrompt,
});
await resources.reload();
const extensions = resources.getExtensions();
assert.deepEqual(extensions.errors, []);
assert.deepEqual(resources.getSkills().diagnostics, []);
assert.deepEqual(resources.getPrompts().diagnostics, []);
record.extensionPaths = extensions.extensions.map((extension) => extension.path);
record.tools = extensions.extensions.flatMap((extension) => [...extension.tools.keys()]);
record.commands = extensions.extensions.flatMap((extension) => [...extension.commands.keys()]);
record.flags = extensions.extensions.flatMap((extension) => [...extension.flags.keys()]);
record.skills = resources.getSkills().skills.map((skill) => skill.name).sort();
record.prompts = resources.getPrompts().prompts.map((prompt) => prompt.name);
record.contextPaths = resources.getAgentsFiles().agentsFiles.map((file) => file.path);
record.appendedInstructions = resources.getAppendSystemPrompt();
record.downloadControls = [
  process.env.PI_LENS_DISABLE_LSP_INSTALL,
  process.env.PI_LENS_DISABLE_TOOL_INSTALL,
];
appendFileSync(process.env.PI_TEST_RECORD, JSON.stringify(record) + "\n");
console.log(JSON.stringify({
  type: "message_end",
  message: {
    role: "assistant",
    content: [{ type: "text", text: "Fixture worker completed" }],
    stopReason: "stop",
  },
}));
