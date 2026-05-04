import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://plagiarismguard.com";

  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/about", "/pricing", "/privacy", "/terms", "/signup"],
        disallow: ["/dashboard", "/login", "/forgot-password", "/verify-email", "/api"],
      },
    ],
    sitemap: `${baseUrl.replace(/\/$/, "")}/sitemap.xml`,
  };
}