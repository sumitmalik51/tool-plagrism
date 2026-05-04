import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import ToastContainer from "@/components/Toast";
import ChatWidget from "@/components/ChatWidget";
import { TooltipProvider } from "@/components/ui";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://plagiarismguard.com"),
  title: "PlagiarismGuard — AI-Powered Academic Plagiarism Detection",
  description:
    "Free AI-powered plagiarism checker for students, researchers & academics. Detect similarity against 250M+ scholarly sources, check grammar, analyze readability, and rewrite with AI.",
  alternates: { canonical: "/" },
  icons: { icon: "/favicon.svg" },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "PlagiarismGuard",
    title: "PlagiarismGuard — AI-Powered Academic Plagiarism Detection",
    description:
      "Detect plagiarism, AI-like text, paraphrases, grammar issues, and citation gaps with academic-grade reports.",
    images: [{ url: "/favicon.svg", alt: "PlagiarismGuard" }],
  },
  twitter: {
    card: "summary",
    title: "PlagiarismGuard — Academic Plagiarism Detection",
    description: "AI-powered originality checking and writing intelligence for researchers and students.",
    images: ["/favicon.svg"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-snippet": -1,
      "max-image-preview": "large",
      "max-video-preview": -1,
    },
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Runs before hydration to set the correct theme and prevent flash.
  const themeInit = `
(function(){try{
  var t = localStorage.getItem('theme');
  if (t !== 'light' && t !== 'dark') {
    t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.setAttribute('data-theme', t);
}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="min-h-full flex flex-col bg-bg text-txt">
        <TooltipProvider delayDuration={200}>
          {children}
          <ToastContainer />
          <ChatWidget />
        </TooltipProvider>
      </body>
    </html>
  );
}
