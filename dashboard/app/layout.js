import { AppRouterCacheProvider } from "@mui/material-nextjs/v15-appRouter";
import Providers from "./providers";

export const metadata = {
  title: "Clearing desk",
  description: "Turn carrier quotes into a client-ready Excel sheet and PDF.",
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
