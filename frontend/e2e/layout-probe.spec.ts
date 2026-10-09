import { expect, shot, test } from "./support/app";
import { setup } from "./support/writing";
import { evidence, sample, workMenu } from "./support/pages";

test("08 版面测量：滚动后导览条与顶栏", async ({ page }, info) => {
  await setup(page);
  // The tour bar is part of the page, not of the top bar: how much of it is visible below the top bar, at the top and scrolled far down.
  const overlap = async () => {
    const banner = await page.getByRole("banner").evaluate(e => e.getBoundingClientRect().toJSON());
    const tour = await page.getByRole("region", { name: "导览", exact: true }).evaluate(e => e.getBoundingClientRect().toJSON());
    const viewport = await page.evaluate(() => innerHeight);
    const shown = { top: Math.max(tour.top, 0), bottom: Math.min(tour.bottom, viewport) };
    return { banner, tour, scrollY: await page.evaluate(() => scrollY), overlap: Math.max(0, Math.min(shown.bottom, banner.bottom) - Math.max(shown.top, banner.top)) };
  };
  const atTop = await overlap();
  expect(atTop.tour.top, "页面顶部：导览条在顶栏下方").toBeGreaterThanOrEqual(atTop.banner.bottom);
  expect(atTop.overlap, "页面顶部：顶栏和导览条没有可见的重叠").toBe(0);
  await page.evaluate(() => window.scrollTo(0, Math.max(1, (document.documentElement.scrollHeight - innerHeight) / 2)));
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  const scrolled = await overlap();
  await evidence(info, "probe-tour", { atTop, scrolled });
  await shot(page, "probe-tour-scrolled", false);
  expect(scrolled.overlap, "滚动后：顶栏和导览条没有可见的重叠").toBe(0);
});

test("08 版面测量：对话框遮罩覆盖视口", async ({ page }, info) => {
  await sample(page);
  await workMenu(page, "重置作品");
  const overlay = await page.getByTestId("dialog-overlay").evaluate(e => e.getBoundingClientRect().toJSON());
  const viewport = await page.evaluate(() => ({ innerWidth, clientWidth: document.documentElement.clientWidth }));
  await evidence(info, "probe-overlay", { overlay, ...viewport });
  await shot(page, "probe-dialog-overlay", false);
  expect(overlay.left).toBe(0);
  expect(overlay.right, "遮罩应覆盖 window.innerWidth").toBeGreaterThanOrEqual(viewport.innerWidth);
  // The top bar's rule runs the full width too (an empty scrollbar gutter used to stop it 15px short).
  const banner = await page.getByRole("banner").evaluate(e => e.getBoundingClientRect().toJSON());
  expect(banner.right, "顶栏（含底线）应覆盖 window.innerWidth").toBeGreaterThanOrEqual(viewport.innerWidth);
});
