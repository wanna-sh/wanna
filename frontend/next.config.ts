import type { NextConfig } from "next";

// The UI is exported as static files and served by the Python backend on the same port.
// In development, set NEXT_PUBLIC_API_BASE=http://localhost:7860 (see .env.development).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
