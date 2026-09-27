/** @type {import('next').NextConfig} */
const nextConfig = {
  // Type checks and lint run during `next build` — do not disable them.
  // NEXT_PUBLIC_API_URL is read by the server-side proxy route at runtime;
  // it does not need to be inlined into the client bundle.
  reactStrictMode: true,
};

export default nextConfig;
