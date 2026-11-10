import type { ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell, Page } from "./components/AppShell";
import { LogoMark } from "./components/brand";
import { LockedArt, LostArt } from "./components/illustrations";
import { ToastProvider } from "./components/toast";
import { Card, EmptyState } from "./components/ui";
import { SessionProvider, useSession } from "./lib/session";
import { ThemeProvider } from "./lib/theme";
import { ChatPage } from "./pages/ChatPage";
import { DocumentPage } from "./pages/DocumentPage";
import { InsightsPage } from "./pages/InsightsPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { LoginPage } from "./pages/LoginPage";

const LINK = "font-medium text-accent-fg underline-offset-2 hover:underline";

/** Shown for the moment it takes the server to say who is signed in. */
function Splash() {
  return (
    <div role="status" aria-label="Loading SourceWise" className="flex h-dvh items-center justify-center bg-canvas">
      <LogoMark className="size-10 animate-pulse-soft" />
    </div>
  );
}

/**
 * Sends signed-out visitors to the sign-in page and remembers where they were going, so a
 * deep link or an expired session returns to the same page after sign-in. After an explicit
 * sign-out nothing is remembered: the next person to sign in may be someone else.
 */
function RequireSession({ children }: { children: ReactNode }) {
  const { status, user, signedOut } = useSession();
  const location = useLocation();
  if (status === "loading") return <Splash />;
  if (!user) return <Navigate to="/login" replace state={signedOut ? null : { from: location.pathname }} />;
  return <>{children}</>;
}

/**
 * Hides admin screens from members. This is a convenience only: the API enforces the same
 * rule on every request, so a member who types the URL gets nothing from the server either.
 */
function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useSession();
  if (user?.role === "admin") return <>{children}</>;
  return (
    <Page title="Administrators only">
      <Card>
        <EmptyState illustration={<LockedArt />} title="You do not have access to this page">
          Managing the knowledge base and viewing insights needs an administrator account.{" "}
          <Link to="/chat" className={LINK}>
            Back to chat
          </Link>
        </EmptyState>
      </Card>
    </Page>
  );
}

function NotFound() {
  return (
    <Page title="Page not found">
      <Card>
        <EmptyState illustration={<LostArt />} title="There is nothing at this address">
          The link may be out of date.{" "}
          <Link to="/chat" className={LINK}>
            Go to chat
          </Link>
        </EmptyState>
      </Card>
    </Page>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <SessionProvider>
        <ToastProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <RequireSession>
                    <AppShell />
                  </RequireSession>
                }
              >
                <Route index element={<Navigate to="/chat" replace />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/chat/:conversationId" element={<ChatPage />} />
                <Route
                  path="/knowledge"
                  element={
                    <AdminOnly>
                      <KnowledgePage />
                    </AdminOnly>
                  }
                />
                <Route
                  path="/knowledge/documents/:documentId"
                  element={
                    <AdminOnly>
                      <DocumentPage />
                    </AdminOnly>
                  }
                />
                <Route
                  path="/insights"
                  element={
                    <AdminOnly>
                      <InsightsPage />
                    </AdminOnly>
                  }
                />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </SessionProvider>
    </ThemeProvider>
  );
}
