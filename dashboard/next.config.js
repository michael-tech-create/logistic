/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allows production verification alongside a running development server.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async rewrites() {
    const api = process.env.API_PROXY_URL || "http://127.0.0.1:8000";
    return [
      { source: "/v1/:path*", destination: `${api}/v1/:path*` },
      { source: "/health", destination: `${api}/health` },
      { source: "/docs", destination: `${api}/docs` },
      { source: "/telegram/:path*", destination: `${api}/telegram/:path*` },
    ];
  },
};
module.exports = nextConfig;
