import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    optimizePackageImports: ["clsx"],
  },
  async rewrites() {
    const api = process.env.STINKY_API_URL || "http://127.0.0.1:8010";
    return [
      {
        source: "/api/stinky/:path*",
        destination: `${api}/:path*`,
      },
    ];
  },
};

export default nextConfig;
