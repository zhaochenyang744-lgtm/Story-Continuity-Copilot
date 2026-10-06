import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";
import "./visual-system.css";
import "./author-context-preview.css";
import "./reference-refresh.css";
import "./maintenance.css";
import "./polish.css";
import "./motion.css";
import "./theme.css";
import "./shell.css";

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
