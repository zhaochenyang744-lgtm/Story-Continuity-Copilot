// Build-time switches.
/** The isolated experience-simulation build: fixed sample data, no real model calls. */
export const experienceSimulation = process.env.NEXT_PUBLIC_EXPERIENCE_SIMULATION === "1";
