import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

/** Validates a Mermaid diagram file: node scripts/validate-mermaid.mjs <file.mmd> */
const file = process.argv[2] ?? "/tmp/diagram.mmd";
const code = readFileSync(file, "utf8");
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent(
  `<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script><div id="c"></div>`,
);
await page.waitForFunction(() => typeof window.mermaid !== "undefined", { timeout: 15_000 });
const result = await page.evaluate(async (code) => {
  try {
    window.mermaid.initialize({ startOnLoad: false });
    await window.mermaid.parse(code);
    const { svg } = await window.mermaid.render("graph1", code);
    return { ok: true, svgLength: svg.length };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}, code);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (!result.ok) process.exit(1);
