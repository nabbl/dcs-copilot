import type { NextConfig } from "next";

const isGitHubPages = process.env.GITHUB_PAGES === "true";

const nextConfig: NextConfig = {
  ...(isGitHubPages
    ? {
        output: "export" as const,
        basePath: "/mara-site",
        assetPrefix: "/mara-site",
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {}),
  webpack(config) {
    config.module.rules.push({
      test: /\.md$/,
      resourceQuery: /raw/,
      type: "asset/source",
    });
    return config;
  },
};

export default nextConfig;
