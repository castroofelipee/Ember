import type { NextConfig } from "next";

// The app is deployed as a Next.js server (standalone output) that proxies
// /api/* to the FastAPI backend, so the browser only ever calls same-origin
// relative paths. BACKEND_URL points at the backend: in dev the local FastAPI
// server, in prod the internal `api` service (see docker-compose.yml). The
// rewrite is compiled during `next build`, so production must provide the value
// as a Docker build argument (see Dockerfile), not only as a runtime variable.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
