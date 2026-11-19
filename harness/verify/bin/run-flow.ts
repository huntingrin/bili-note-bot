import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

type FlowModule = {
  run: (context: {
    root: string;
    baseUrl: string;
    artifactsDir: string;
  }) => Promise<void>;
};

async function main() {
  const args = process.argv.slice(2);
  const flowIndex = args.indexOf("--flow");
  const flowId = flowIndex >= 0 ? args[flowIndex + 1] : "app.boot";

  if (!flowId) {
    throw new Error("Usage: verify --flow <id>");
  }

  const root = process.cwd();
  const baseUrl = process.env.BASE_URL ?? "http://localhost:3000";
  const runId = new Date().toISOString().replace(/[:.]/g, "-");
  const artifactsDir = path.join(
    root,
    "harness/verify/artifacts",
    `${runId}-${flowId}`,
  );

  await mkdir(artifactsDir, { recursive: true });

  const report: Record<string, unknown> = {
    flow: flowId,
    status: "fail",
    baseUrl,
    startedAt: new Date().toISOString(),
    artifactsDir,
  };

  try {
    // CLI projects have no dev server. Set VERIFY_SKIP_HTTP=1 to skip the
    // reachability precheck; the flow itself asserts the real postcondition.
    if (process.env.VERIFY_SKIP_HTTP !== "1") {
      const reachable = await fetch(baseUrl)
        .then(() => true)
        .catch(() => false);

      if (!reachable) {
        throw new Error(
          `App is not reachable at ${baseUrl}. Start it with 'pnpm dev' or 'bash harness/verify/bin/boot.sh'.`,
        );
      }
    }

    const flowPath = path.join(root, "harness/verify/flows", `${flowId}.ts`);
    const flow = (await import(pathToFileURL(flowPath).href)) as FlowModule;

    if (typeof flow.run !== "function") {
      throw new Error(`Flow ${flowId} does not export a run() function`);
    }

    await flow.run({ root, baseUrl, artifactsDir });
    report.status = "pass";
  } catch (error) {
    report.error = error instanceof Error ? error.message : String(error);
  } finally {
    report.finishedAt = new Date().toISOString();
    await writeFile(
      path.join(artifactsDir, "report.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report, null, 2));
  }

  if (report.status !== "pass") {
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
