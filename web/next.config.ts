import type { NextConfig } from "next";

// Production builds are exported as static assets (web/out) and served by
// the FastAPI server, so one process ships the whole app. In dev, Next runs
// its own server and proxies /api to the FastAPI dev server instead.
const isProdBuild = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  output: isProdBuild ? "export" : undefined,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
