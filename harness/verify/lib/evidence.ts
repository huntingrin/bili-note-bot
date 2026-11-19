import { writeFile } from "node:fs/promises";
import path from "node:path";
import type { Page } from "playwright";

export async function screenshot(
  page: Page,
  dir: string,
  name: string,
): Promise<string> {
  const file = path.join(dir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

export async function saveJson(
  dir: string,
  name: string,
  value: unknown,
): Promise<string> {
  const file = path.join(dir, `${name}.json`);
  await writeFile(file, JSON.stringify(value, null, 2));
  return file;
}
