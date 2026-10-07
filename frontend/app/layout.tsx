import type { Metadata, Viewport } from "next";
import Script from "next/script";
// 朱批 stylesheets (v1.7.0): tokens first, then elements, the app frame, shared components, one file
// per page area, and motion last.
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/components.css";
import "./styles/pages/global.css";
import "./styles/pages/overview.css";
import "./styles/pages/workspace.css";
import "./styles/pages/chapters.css";
import "./styles/pages/materials.css";
import "./styles/pages/plan.css";
import "./styles/pages/guide.css";
import "./styles/pages/author-context.css";
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
