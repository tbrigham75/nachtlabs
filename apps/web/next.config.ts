import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  transpilePackages: ["@nachtlabs/api-client"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NACHTLABS_INTERNAL_API_URL ?? "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
};
export default config;
