import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Desktop-panel only: loaded explicitly by launch-pi-panel, not globally. */
export default function (pi: ExtensionAPI) {
  let lastStopReason: string | undefined;

  pi.on("agent_start", async () => {
    lastStopReason = undefined;
  });

  pi.on("message_end", async (event) => {
    if (event.message.role === "assistant") {
      lastStopReason = event.message.stopReason;
    }
  });

  // agent_end may precede automatic retries, compaction, and queued follow-ups.
  // agent_settled is the final notification-only boundary for the whole run.
  pi.on("agent_settled", async (event, ctx) => {
    const completed = lastStopReason === "stop" || lastStopReason === "length";
    lastStopReason = undefined;
    if (ctx.mode !== "tui" || event.aborted || !completed) return;

    try {
      await pi.exec("notify-send", [
        "--app-name=Desktop Pi",
        "--icon=utilities-terminal",
        "--expire-time=7000",
        "Desktop Pi finished responding",
        "Super + A to open the agent",
      ], { timeout: 3000 });
    } catch {
      // A missing/restarting notification server must not disrupt the agent.
    }
  });
}
