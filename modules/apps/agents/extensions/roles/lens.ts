import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/**
 * Initialize the pinned, diagnostics-only Lens extension for either agent role.
 *
 * Disable Lens-managed tool and language-server downloads before initialization.
 * Automatic formatting, lint fixes, and warning quickfixes must remain disabled
 * regardless of CLI, global, project, or nested-project configuration. Explicit
 * agent-requested edits remain subject to the agent's approved task scope.
 *
 * Reject if initialization fails; never silently fall back to unpatched Lens.
 */
export async function registerDiagnosticLens(pi: ExtensionAPI): Promise<void> {
  process.env.PI_LENS_DISABLE_LSP_INSTALL = "1";
  process.env.PI_LENS_DISABLE_TOOL_INSTALL = "1";

  const lens = await import("../node_modules/pi-lens/dist/index.js");
  if (typeof lens.resolveNixLensFlag !== "function") {
    throw new Error("Lens diagnostics-only policy is missing; refusing to initialize");
  }

  const requiredFlags = {
    "no-autoformat": true,
    "no-autofix": true,
    "lens-actionable-warning-autofix": false,
  };
  // Probe conflicting CLI values: an export marker alone would not verify policy.
  for (const [name, expected] of Object.entries(requiredFlags)) {
    const resolved = lens.resolveNixLensFlag(name, !expected);
    if (resolved?.value !== expected || resolved?.source !== "nix-policy") {
      throw new Error(`Lens diagnostics-only policy failed for ${name}; refusing to initialize`);
    }
  }

  await lens.default(pi);
}
