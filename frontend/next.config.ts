import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), usb=(), bluetooth=(), serial=(), hid=(), keyboard-map=(), gamepad=(), notifications=(), display-capture=(), window-management=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
