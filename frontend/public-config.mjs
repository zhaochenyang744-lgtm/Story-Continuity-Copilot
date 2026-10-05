function canonicalOrigin(value, { httpsOnly = false } = {}) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("PUBLIC_BASE_URL_INVALID: expected a canonical origin");
  }
  if (
    (httpsOnly ? parsed.protocol !== "https:" : !["http:", "https:"].includes(parsed.protocol)) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    parsed.origin !== value
  ) {
    throw new Error("PUBLIC_BASE_URL_INVALID: expected a canonical origin");
  }
  return parsed;
}

export function validatePublicConfig(env, { required = false } = {}) {
  const rawMode = env.PUBLIC_APP_MODE;
  if (required && !["0", "1"].includes(rawMode)) {
    throw new Error("PUBLIC_APP_MODE_REQUIRED: production builds require explicit 0 or 1");
  }
  if (rawMode !== undefined && !["0", "1"].includes(rawMode)) {
    throw new Error("PUBLIC_APP_MODE_INVALID: expected 0 or 1");
  }
  const publicMode = rawMode === "1";
  if (required && !env.PUBLIC_BASE_URL) {
    throw new Error("PUBLIC_BASE_URL_REQUIRED: production builds require an explicit public origin");
  }
  const value = env.PUBLIC_BASE_URL || "http://127.0.0.1:3080";
  const parsed = canonicalOrigin(value, { httpsOnly: publicMode });
  if (!publicMode && (parsed.hostname !== "127.0.0.1" || parsed.port === "")) {
    throw new Error("PUBLIC_BASE_URL_INVALID: local mode requires explicit 127.0.0.1 port");
  }
  return { publicMode, publicBaseUrl: parsed.origin };
}
