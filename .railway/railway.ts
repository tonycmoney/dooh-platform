// Railway infrastructure for the DOOH platform (replaces railway.json).
//
// Whole-project management: anything removed from this file is removed from
// Railway on `railway config apply`, so keep the database and both volumes
// here. Variables are unmanaged: they're set in Railway (secrets never live in
// this repo). Preview changes with `railway config plan` before applying.
import { defineRailway, postgres, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const volumeSettings = {
    alerts: { usage: { "100": {}, "80": {}, "95": {} } },
    allowOnlineResize: true,
    region: "iad",
    sizeMB: 5000,
  };

  const Postgres = postgres("Postgres", { region: "iad" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", volumeSettings);

  // Formatted media, kept originals and daily database dumps.
  const doohVolume = volume("dooh-volume", volumeSettings);

  // The backend, serving the API, media and the built dashboard (Dockerfile).
  const dooh = service("dooh", {
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: {
      healthcheckPath: "/api/health",
      healthcheckTimeout: 120,
      restartPolicyType: "ALWAYS",
    },
    replicas: { iad: 1 },
    volumeMounts: { "/data": doohVolume },
  });
  dooh.networking = { serviceDomains: { "dooh-production.up.railway.app": {} } };

  return project("dooh-platform", {
    variables: { managed: false },
    resources: [Postgres, dooh, postgresVolume, doohVolume],
  });
});
