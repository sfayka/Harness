import type { NextConfig } from "next";

const isStaticDashboardExport = process.env.HARNESS_DASHBOARD_OUTPUT === "export";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  basePath: isStaticDashboardExport ? "/dashboard" : undefined,
  output: isStaticDashboardExport ? "export" : undefined,
  trailingSlash: isStaticDashboardExport ? true : undefined,
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
