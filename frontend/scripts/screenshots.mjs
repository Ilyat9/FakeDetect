/**
 * Generates README screenshots into ../docs/screenshots/.
 *
 * Usage:  npm run dev (in another terminal) && node scripts/screenshots.mjs
 * API responses are mocked with representative demo data so the shots are
 * deterministic and never trigger real LLM calls.
 */
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const BASE = process.env.SHOT_BASE_URL ?? "http://localhost:5173";
const OUT = new URL("../../docs/screenshots/", import.meta.url).pathname;

const SESSION = JSON.stringify({ apiKey: "demo", role: "owner", tenantId: null });

const day = (offset) => {
  const d = new Date(Date.now() - offset * 86_400_000);
  return d.toISOString().slice(0, 10);
};

const timeseries = {
  points: Array.from({ length: 30 }, (_, i) => {
    const o = 29 - i;
    const total = 18 + Math.round(22 * Math.abs(Math.sin(i / 4))) + (i % 5);
    return { date: day(o), total, fakes: Math.round(total * 0.34) };
  }),
};

const topSellers = {
  sellers: [
    { seller: "technoshop_fake", marketplace: "WB", checks: 64, fakes: 51 },
    { seller: "brand_outlet_777", marketplace: "OZON", checks: 48, fakes: 39 },
    { seller: "originals_market", marketplace: "WB", checks: 41, fakes: 27 },
    { seller: "discount_zone", marketplace: "YM", checks: 33, fakes: 19 },
    { seller: "mega_sklad", marketplace: "WB", checks: 22, fakes: 11 },
  ],
};

const cases = [
  ["AirPods Pro 2 — копия", "WB", "technoshop_fake", "CONFIRMED_FAKE"],
  ["Кроссовки Nike Air Force", "OZON", "brand_outlet_777", "COMPLAINT_FILED"],
  ["Духи Dior Sauvage", "WB", "originals_market", "UNDER_REVIEW"],
  ["Наушники Sony WH-1000XM5", "YM", "discount_zone", "LISTING_REMOVED"],
  ["Футболка The North Face", "WB", "mega_sklad", "DETECTED"],
  ["Часы Casio G-Shock", "OZON", "technoshop_fake", "CLOSED"],
  ["Рюкзак Herschel", "WB", "brand_outlet_777", "FALSE_POSITIVE"],
  ["Пуховик Uniqlo", "YM", "originals_market", "UNDER_REVIEW"],
].map(([url, marketplace, seller, status], i) => ({
  id: 101 + i,
  check_id: 501 + i,
  url: `https://www.wildberries.ru/catalog/${20000000 + i}/detail.aspx`,
  brand: "Demo Brand",
  marketplace,
  seller,
  verdict: "ПОДДЕЛКА",
  status,
  assignee: i % 2 ? "a.ivanova" : "d.petrov",
  sla_deadline: null,
  created_at: new Date(Date.now() - (i + 1) * 36e5 * 12).toISOString(),
  updated_at: new Date(Date.now() - i * 36e5).toISOString(),
}));

async function mockApi(page) {
  await page.route("**/api/v1/stats", (r) =>
    r.fulfill({ json: { total: 1284, fakes: 412, originals: 631, suspicious: 241 } }));
  await page.route("**/api/v1/analytics/timeseries", (r) => r.fulfill({ json: timeseries }));
  await page.route("**/api/v1/analytics/top-sellers", (r) => r.fulfill({ json: topSellers }));
  await page.route("**/api/v1/analytics/revenue", (r) =>
    r.fulfill({
      json: {
        protected_revenue: 2_840_000,
        methodology:
          "Оценка предотвращённого ущерба: подтверждённые подделки × средняя цена оригинала за период",
        period_days: 30,
      },
    }));
  await page.route("**/api/v1/analytics/timing", (r) =>
    r.fulfill({ json: { avg_time_to_detection_hours: 5.2, avg_time_to_resolution_hours: 49.7 } }));
  await page.route("**/api/v1/cases*", (r) => r.fulfill({ json: { cases, total: cases.length } }));
  await page.route("**/api/v1/watches*", (r) =>
    r.fulfill({
      json: {
        watches: [
          {
            id: 7,
            brand_name: "Demo Brand",
            keywords: "demo brand, demo original",
            marketplaces: "WB,OZON,YM",
            cron_schedule: "0 7 * * *",
            digest_interval_hours: 24,
            is_active: 1,
            last_run_at: new Date(Date.now() - 7_200_000).toISOString(),
            next_run_at: new Date(Date.now() + 57_600_000).toISOString(),
            last_status: "ok",
            created_at: new Date(Date.now() - 30 * 86_400_000).toISOString(),
          },
          {
            id: 8,
            brand_name: "Second Label",
            keywords: "second label",
            marketplaces: "WB",
            cron_schedule: "0 7 * * 1",
            digest_interval_hours: 24,
            is_active: 1,
            last_run_at: new Date(Date.now() - 172_800_000).toISOString(),
            next_run_at: new Date(Date.now() + 430_000_000).toISOString(),
            last_status: "ok",
            created_at: new Date(Date.now() - 14 * 86_400_000).toISOString(),
          },
        ],
        total: 2,
      },
    }));
  await page.route("**/api/v1/watches/7/listings*", (r) =>
    r.fulfill({
      json: {
        listings: [
          { id: 1, watch_id: 7, url: "https://www.wildberries.ru/catalog/90000001/detail.aspx", sku: "90000001", title: "Demo Brand наушники беспроводные", price: 1890, seller: "technoshop_fake", thumbnail_url: null, status: "analyzed", verdict: "ПОДДЕЛКА", discovered_at: new Date(Date.now() - 3_600_000).toISOString() },
          { id: 2, watch_id: 7, url: "https://www.wildberries.ru/catalog/90000002/detail.aspx", sku: "90000002", title: "Demo Brand чехол оригинал", price: 990, seller: "originals_market", thumbnail_url: null, status: "analyzed", verdict: "ОРИГИНАЛ", discovered_at: new Date(Date.now() - 7_200_000).toISOString() },
          { id: 3, watch_id: 7, url: "https://www.wildberries.ru/catalog/90000003/detail.aspx", sku: "90000003", title: "Demo Brand зарядное устройство", price: 1290, seller: "discount_zone", thumbnail_url: null, status: "new", verdict: null, discovered_at: new Date(Date.now() - 1_800_000).toISOString() },
        ],
        total: 3,
      },
    }));
  await page.route("**/api/v1/analyze*", (r) =>
    r.fulfill({
      json: {
        verdict: "ПОДДЕЛКА",
        confidence: 91,
        summary:
          "Логотип смещён относительно эталона, шрифт надписи отличается. Заявленная цена в 3 раза ниже официальной — типичный признак контрафакта.",
        provider: "Gemini 2.5 Flash Vision",
        indicators: [
          { factor: "pHash similarity", score: 0.82, detail: "расстояние 6 из 64" },
          { factor: "ELA score", score: 0.74, detail: "признаки редактирования изображения" },
          { factor: "LLM consensus", score: 0.95, detail: "2/2 провайдера согласны" },
        ],
      },
    }));
}

async function settle(page, ms = 700) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(ms);
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  await page.addInitScript(`sessionStorage.setItem("fakedetect-session-hmr", '${SESSION}')`);
  await mockApi(page);

  // 1. Dashboard
  await page.goto(`${BASE}/`);
  await settle(page, 1200);
  await page.screenshot({ path: `${OUT}dashboard.png`, fullPage: true });

  // 2. Analyze -> verdict
  await page.goto(`${BASE}/analyze`);
  await settle(page);
  await page.getByText("URL маркетплейса").click();
  await page.getByPlaceholder(/wildberries\.ru/).fill("https://www.wildberries.ru/catalog/20000001/detail.aspx");
  await page.getByRole("button", { name: "Проверить" }).click();
  await page.getByText("ПОДДЕЛКА").first().waitFor({ timeout: 5000 });
  await page.locator("details summary").click(); // expand forensic breakdown
  await page.waitForTimeout(4_500); // let the success toast auto-dismiss
  await settle(page, 400);
  await page.screenshot({ path: `${OUT}verdict.png` });

  // 3. Cases kanban
  await page.goto(`${BASE}/cases`);
  await settle(page, 900);
  await page.getByRole("button", { name: "Канбан" }).click();
  await settle(page, 500);
  await page.screenshot({ path: `${OUT}cases.png`, fullPage: true });

  // 4. Brand watches with findings feed
  await page.goto(`${BASE}/watches`);
  await settle(page, 900);
  await page.getByText("Demo Brand").first().click();
  await page.getByText("Лента находок").waitFor({ timeout: 5000 });
  await settle(page, 500);
  await page.screenshot({ path: `${OUT}watches.png`, fullPage: true });

  await browser.close();
  console.log(`Screenshots written to ${OUT}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});


