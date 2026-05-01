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
  title: "PlagiarismGuard — AI-Powered Academic Plagiarism Detection",
  description:
    "Free AI-powered plagiarism checker for students, researchers & academics. Detect similarity against 250M+ scholarly sources, check grammar, analyze readability, and rewrite with AI.",
  icons: { icon: "/favicon.svg" },
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
