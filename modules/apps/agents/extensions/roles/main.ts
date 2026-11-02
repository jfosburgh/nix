import { readFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerQuestions from "../node_modules/@juicesharp/rpiv-ask-user-question/index.ts";
import registerTodo from "../node_modules/@juicesharp/rpiv-todo/index.ts";
import registerSubagent from "../subagent/index.ts";
import registerUsage from "../node_modules/@narumitw/pi-usage/dist/index.ts";
import registerSplitView from "../node_modules/pi-split-view/split-view.ts";
import { registerDiagnosticLens } from "./lens.ts";

/**
 * Initialize the supervisor's question, todo, diagnostic Lens, delegation,
 * provider usage and split-view extensions, and attach the supervisor policy
 * only to this agent's prompts.
 *
 * Preserve locally managed packages and model settings. Initialization failure
 * must reject rather than leave a partially registered supervisor loadout.
 */
export default async function main(pi: ExtensionAPI): Promise<void> {
  const policy = readFileSync(new URL("./supervisor.md", import.meta.url), "utf8").trim();
  if (!policy) {
    throw new Error("Development supervisor policy is empty; refusing to initialize");
  }

  await registerDiagnosticLens(pi);
  registerQuestions(pi);
  registerTodo(pi);
  registerSubagent(pi);
  registerUsage(pi);
  registerSplitView(pi);

  // A stable section preserves other instructions and avoids appending policy each turn.
  pi.on("before_agent_start", function applySupervisorPolicy(event) {
    event.systemPromptOptions.sections.development_supervisor = policy;
  });
}
