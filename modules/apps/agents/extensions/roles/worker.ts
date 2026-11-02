import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDiagnosticLens } from "./lens.ts";

/**
 * Initialize diagnostic Lens for a coding worker, without supervisor policy,
 * interactive question/todo extensions, wiki hooks, or recursive delegation.
 *
 * The caller must disable discovered extensions and explicitly select this
 * entry point. This factory cannot unload extensions the caller already loaded.
 */
export default async function worker(pi: ExtensionAPI): Promise<void> {
  await registerDiagnosticLens(pi);
}
