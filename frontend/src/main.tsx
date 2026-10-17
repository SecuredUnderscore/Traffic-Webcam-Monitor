import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { ToastProvider } from "./components/ui";
import "./styles.css";
import { applyTheme, getTheme } from "./util";

applyTheme(getTheme());

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: true, staleTime: 2000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
