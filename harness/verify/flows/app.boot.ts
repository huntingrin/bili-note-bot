import { execFile } from "node:child_process";
import { copyFile, readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { assert } from "../lib/assert";
import { saveJson } from "../lib/evidence";

const exec = promisify(execFile);

function pngSize(buf: Buffer) {
  assert(buf.subarray(1, 4).toString() === "PNG", "out/card.png is not a PNG");
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

/**
 * CLI first flow: the product is a command, not a web page.
 * `python3 main.py --selftest` renders a card from a built-in fixture;
 * we then verify the artifact itself (PNG magic + exact pixel size).
 */
export async function run({
  root,
  artifactsDir,
}: {
  root: string;
  baseUrl: string;
  artifactsDir: string;
}) {
  const startedAt = Date.now();

  const { stdout, stderr } = await exec("python3", ["main.py", "--selftest"], {
    cwd: root,
    timeout: 180_000,
    maxBuffer: 10 * 1024 * 1024,
  });

  const cardPath = path.join(root, "out", "card.png");
  const buf = await readFile(cardPath);
  const size = pngSize(buf);

  assert(
    size.width === 1080,
    `expected card width 1080, got ${size.width}`,
  );
  assert(
    size.height === 1440,
    `expected card height 1440, got ${size.height}`,
  );

  await copyFile(cardPath, path.join(artifactsDir, "card.png"));
  await saveJson(artifactsDir, "run", {
    command: "python3 main.py --selftest",
    exitCode: 0,
    stdout: stdout.trim().slice(-2000),
    stderr: stderr.trim().slice(-2000),
    card: { width: size.width, height: size.height, bytes: buf.length },
    durationMs: Date.now() - startedAt,
  });

  console.log(
    `app.boot ok: card ${size.width}x${size.height} (${buf.length} bytes)`,
  );
}
