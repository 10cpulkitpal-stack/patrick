/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: false,
  images: {
    unoptimized: true,
  },
  experimental: {
    webpackMemoryOptimizations: true,
  },
}

export default nextConfig
