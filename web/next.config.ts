import type { NextConfig } from "next";

// GitHub Pages serves the site under /<repo>. Override with
// NEXT_PUBLIC_BASE_PATH="" for local previews at the root.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "/RootLine";

const nextConfig: NextConfig = {
  output: "export",
  basePath: basePath || undefined,
  trailingSlash: true,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
};

export default nextConfig;
