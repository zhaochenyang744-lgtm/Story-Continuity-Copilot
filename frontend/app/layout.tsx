import type { Metadata, Viewport } from "next";
import Script from "next/script";
// Self-hosted fonts, sliced by unicode-range so a page only fetches the characters it shows.
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/700.css";
import "@fontsource/noto-sans-sc/900.css";
import "@fontsource/noto-serif-sc/400.css";
import "@fontsource/noto-serif-sc/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource-variable/archivo/wdth.css";
// 版面 stylesheets (v1.7.0): tokens, elements, the shared frame, then one file per page.
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/frame.css";
import "./styles/pages/home.css";
import "./styles/pages/global.css";
import "./styles/pages/overview.css";
import "./styles/pages/writing.css";
import "./styles/pages/chapters.css";
import "./styles/pages/materials.css";
import "./styles/pages/plan.css";
import "./styles/motion.css";

export const metadata: Metadata = {
  title: "Story Continuity Copilot",
  description: "中文长篇小说连续性审阅工作台",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

const themeBootScript = `try{document.documentElement.dataset.theme=localStorage.getItem("story-continuity:theme")==="night"?"night":"day"}catch(e){}`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        {children}
        {/* Apply the remembered day/night choice before the app hydrates. */}
        <Script id="theme-boot" strategy="beforeInteractive">{themeBootScript}</Script>
      </body>
    </html>
  );
}
