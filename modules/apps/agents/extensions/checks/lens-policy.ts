import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resolveNixLensFlag as resolveEntryFlag } from "../node_modules/pi-lens/dist/index.js";
import { resolveNixLensFlag as resolveChunkFlag } from "../node_modules/pi-lens/dist/chunk-WMDUT4KH.js";
import { registerDiagnosticLens } from "../roles/lens.ts";

/** Check both real resolvers and initialize Lens without starting a session. */
export default async function checkLensPolicy(pi: ExtensionAPI): Promise<void> {
  const projectRoot = mkdtempSync(join(tmpdir(), "pi-lens-policy-"));
  const enabled = {
    format: { enabled: true },
    autofix: { enabled: true },
    actionableWarnings: { autoFix: { enabled: true } },
  };
  const disabled = {
    format: { enabled: false },
    autofix: { enabled: false },
    actionableWarnings: { autoFix: { enabled: false } },
  };

  try {
    const nestedRoot = join(projectRoot, "nested");
    mkdirSync(nestedRoot);
    writeFileSync(join(projectRoot, ".pi-lens.json"), JSON.stringify(disabled));
    writeFileSync(join(nestedRoot, ".pi-lens.json"), JSON.stringify(enabled));
    const nestedFile = join(nestedRoot, "example.ts");
    writeFileSync(nestedFile, "const value = 1;\n");

    for (const resolve of [resolveEntryFlag, resolveChunkFlag]) {
      for (const [name, expected] of [
        ["no-autoformat", true],
        ["no-autofix", true],
        ["lens-actionable-warning-autofix", false],
      ] as const) {
        for (const cliValue of [undefined, false, true]) {
          for (const [globalConfig, projectConfig] of [
            [undefined, undefined],
            [enabled, undefined],
            [undefined, enabled],
            [disabled, enabled],
          ]) {
            assert.deepEqual(
              resolve(name, cliValue, globalConfig, projectConfig, nestedFile, projectRoot),
              { value: expected, source: "nix-policy" },
              `${name} must ignore CLI, global, project and nested-project overrides`,
            );
          }
        }
      }

      // The patch must leave unrelated configuration and CLI precedence alone.
      assert.deepEqual(resolve("no-tests", true, { tests: { enabled: true } }), {
        value: true,
        source: "cli",
      });
      assert.deepEqual(resolve("no-tests", undefined, { tests: { enabled: false } }), {
        value: true,
        source: "global",
      });
      assert.deepEqual(resolve("no-tests", undefined, { tests: { enabled: true } }), {
        value: false,
        source: "global",
      });
    }

    // Simulate a shell attempting to allow managed downloads.
    process.env.PI_LENS_DISABLE_LSP_INSTALL = "0";
    process.env.PI_LENS_DISABLE_TOOL_INSTALL = "0";
    await registerDiagnosticLens(pi);
    assert.equal(process.env.PI_LENS_DISABLE_LSP_INSTALL, "1");
    assert.equal(process.env.PI_LENS_DISABLE_TOOL_INSTALL, "1");
  } finally {
    rmSync(projectRoot, { recursive: true, force: true });
  }
}
