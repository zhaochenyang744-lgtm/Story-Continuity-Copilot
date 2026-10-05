const DEVELOPMENT_BACKEND_ORIGIN = "http://127.0.0.1:8000";

export function validateBackendOrigin(value, { required = false } = {}) {
  if (!value) {
    if (required) {
      throw new Error(
        "BACKEND_ORIGIN_REQUIRED: production builds require an explicit backend origin",
      );
    }
    return DEVELOPMENT_BACKEND_ORIGIN;
  }

  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("BACKEND_ORIGIN_INVALID: expected a canonical http(s) origin");
  }

  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    parsed.origin !== value
  ) {
    throw new Error(
      "BACKEND_ORIGIN_INVALID: paths, queries, fragments, credentials, and non-http(s) schemes are forbidden",
    );
  }

  return parsed.origin;
}
