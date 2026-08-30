export type Stage13HarnessProfile = "impl" | "pm3";

export type Stage13Harness = {
  profileName: Stage13HarnessProfile;
  frontendOrigin: string;
  backendOrigin: string;
  distDir: string;
  tempPrefix: string;
  frontendPort: number;
  backendPort: number;
  accountPrefix: string;
  testRoot: string;
  outputDir: string;
};

export function validateStage13Harness(env: Record<string, string | undefined>): Stage13Harness;
