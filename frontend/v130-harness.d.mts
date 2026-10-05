export type V130Harness = {
  name: "localrc";
  frontendOrigin: string;
  backendOrigin: string;
  distDir: string;
  tempPrefix: string;
  frontendPort: number;
  backendPort: number;
  accountPrefix: string;
  testRoot: string;
  outputDir: string;
  reportDir: string;
  jsonReport: string;
  providerStats: string;
  lastRun: string;
  artifactRoot: string;
};

export declare const V130_PROFILE: Readonly<{
  name: "localrc";
  frontendOrigin: string;
  backendOrigin: string;
  distDir: string;
  tempPrefix: string;
  accountPrefix: string;
}>;

export function validateV130Harness(env: Record<string, string | undefined>): V130Harness;
