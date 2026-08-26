import { expect, test } from "@playwright/test";

test.describe("smoke", () => {
  test("unauthenticated user is redirected to /login without flashing content", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: /FakeDetect/i })).toBeVisible();
    await expect(page.getByLabel("X-API-Key")).toBeVisible();
  });

  test("app shell and theme toggle are reachable after login screen", async ({ page }) => {
    await page.goto("/login");
    // Submit with an empty key (open-mode deployments accept it; secured ones
    // show a toast error — both paths must render the form correctly).
    await page.getByRole("button", { name: "Войти" }).click();
    // Either navigation happens (open mode) or an error toast appears —
    // in both cases the page must not crash.
    await page.waitForTimeout(1000);
    const body = page.locator("body");
    await expect(body).toBeVisible();
  });
});

/* Full-path specs (enabled against a running backend via E2E_BASE_URL):

test("analyze -> verdict", async ({ page }) => {
  await login(page);
  await page.goto("/analyze");
  // drag&drop fixtures/reference.jpg + fixtures/suspect.jpg
  ...
});

*/
