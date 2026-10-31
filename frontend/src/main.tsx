import { Globals } from "@react-spring/web";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "highlight.js/styles/github-dark.css";
import "./index.css";
import { App } from "./App";
import { AuthGate } from "./components/AuthGate";

const queryClient = new QueryClient({
  // No polling or focus refetch: requests happen only on user actions.
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false, staleTime: Infinity } },
});

// Springs jump straight to their end state when the OS asks for reduced motion.
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
Globals.assign({ skipAnimation: reduceMotion.matches });
reduceMotion.addEventListener("change", (e) => Globals.assign({ skipAnimation: e.matches }));

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <App />
      </AuthGate>
    </QueryClientProvider>
  </StrictMode>,
);
