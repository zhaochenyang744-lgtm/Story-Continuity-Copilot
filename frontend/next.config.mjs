import { validateBackendOrigin } from "./build-origin.mjs";
import { optionalBuildId } from "./build-id.mjs";
import { validatePublicConfig } from "./public-config.mjs";

const backendOrigin = validateBackendOrigin(process.env.BACKEND_ORIGIN, {
  required: process.env.NODE_ENV === "production",
});
const publicConfig = validatePublicConfig(process.env, {
  required: process.env.NODE_ENV === "production",
});
const buildId = optionalBuildId(process.env.NEXT_BUILD_ID);

const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig = {
  output: "standalone",
  ...(buildId ? { generateBuildId: async () => buildId } : {}),
  // An optional build directory keeps local verification from taking an
  // active developer server's default `.next` lock. Production keeps `.next`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  async headers() {
    const headers = [
      { key: "Content-Security-Policy", value: contentSecurityPolicy },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ];
    if (publicConfig.publicMode) {
      headers.push({ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" });
    }
    return [{ source: "/:path*", headers }];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendOrigin}/api/:path*` },
    ];
  },
};

export default nextConfig;
