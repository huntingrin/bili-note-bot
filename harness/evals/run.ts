import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

async function main() {
  const root = process.cwd();
  const runId = new Date().toISOString().replace(/[:.]/g, "-");
  const runDir = path.join(root, "harness/evals/runs", runId);

  await mkdir(runDir, { recursive: true });

  let status: "pass" | "fail" = "pass";

  try {
    execFileSync(
      "npx",
      ["tsx", "harness/verify/bin/run-flow.ts", "--flow", "app.boot"],
      {
        stdio: "inherit",
        cwd: root,
      },
    );
  } catch {
    status = "fail";
  }

  await writeFile(
    path.join(runDir, "result.json"),
    JSON.stringify(
      {
        case: "001-app-boot",
        status,
        at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );

  if (status !== "pass") {
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
