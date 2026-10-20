import { AppRouterCacheProvider } from "@mui/material-nextjs/v15-appRouter";
import Providers from "./providers";

export const metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "http://localhost:3000")),
  title: "Clearing desk",
  icons: {
    icon: [{ url: "/clearing-desk-icon-32.png", sizes: "32x32", type: "image/png" }, { url: "/clearing-desk-logo-192.webp", sizes: "192x192", type: "image/webp" }],
    apple: [{ url: "/clearing-desk-icon-180.png", sizes: "180x180", type: "image/png" }],
  },
  description: "Collect freight quotes, check shipment details and charges, and prepare client files in one workspace.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AppRouterCacheProvider>
          <Providers>{children}</Providers>
        </AppRouterCacheProvider>
      </body>
    </html>
  );
}
