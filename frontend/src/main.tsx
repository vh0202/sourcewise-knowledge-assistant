// Inter with its optical-size axis: large headings get the tighter display cut automatically.
import "@fontsource-variable/inter/opsz.css";
import "./index.css";

import { LucideProvider } from "lucide-react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    {/* Icons are drawn with a slightly lighter stroke than the library default. */}
    <LucideProvider strokeWidth={1.75}>
      <App />
    </LucideProvider>
  </StrictMode>,
);
