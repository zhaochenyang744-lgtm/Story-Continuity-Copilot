import { expect, shot, test } from "./support/app";
import { setup } from "./support/writing";
import { evidence, sample, workMenu } from "./support/pages";

test("08 版面测量：滚动后导览条与顶栏", async ({ page }, info) => {
  test.fixme(true, "清单第 22 条：scrollY=1955 时导览条 top=-1869、bottom=-1794.203125，滚出了视口；不满足位于顶栏下方的要求，并非可见重叠");
  await setup(page);
  await page.evaluate(() => window.scrollTo(0, Math.max(1, (document.documentElement.scrollHeight - innerHeight) / 2)));
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  const banner = await page.getByRole("banner").evaluate(e => e.getBoundingClientRect().toJSON());
  const tour = await page.getByRole("region", { name: "导览", exact: true }).evaluate(e => e.getBoundingClientRect().toJSON());
  await evidence(info, "probe-tour", { banner, tour, scrollY: await page.evaluate(() => scrollY) });
  await shot(page, "probe-tour-scrolled", false);
  expect(tour.top, "清单第 22 条：导览条应位于顶栏下方且不重叠").toBeGreaterThanOrEqual(banner.bottom);
});

test("08 版面测量：对话框遮罩覆盖视口", async ({ page }, info) => {
  test.fixme(true, "清单第 23 条：遮罩 right=1425，innerWidth/clientWidth=1440，右侧 15px 未覆盖");
  await sample(page);
  await workMenu(page, "重置作品");
  const overlay = await page.getByTestId("dialog-overlay").evaluate(e => e.getBoundingClientRect().toJSON());
  const viewport = await page.evaluate(() => ({ innerWidth, clientWidth: document.documentElement.clientWidth }));
  await evidence(info, "probe-overlay", { overlay, ...viewport });
  await shot(page, "probe-dialog-overlay", false);
  expect(overlay.left).toBe(0);
  expect(overlay.right, "清单第 23 条：遮罩应覆盖 window.innerWidth").toBeGreaterThanOrEqual(viewport.innerWidth);
});
