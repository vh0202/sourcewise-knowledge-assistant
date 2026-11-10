import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, onUnauthorized } from "./api";
import type { Meta, User } from "./types";

interface SessionState {
  /** "loading" until the first round trip (who is signed in, and the app metadata) has finished. */
  status: "loading" | "ready";
  user: User | null;
  /** True after the user chose "Sign out", as opposed to a session that expired. */
  signedOut: boolean;
  meta: Meta | null;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

/** Holds who is signed in (the server decides; this only mirrors it) and the app metadata. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionState["status"]>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    let cancelled = false;
    const metaLoaded = api
      .meta()
      .then((value) => !cancelled && setMeta(value))
      .catch(() => undefined);
    const sessionLoaded = api
      .session()
      .then((value) => !cancelled && setUser(value))
      .catch(() => !cancelled && setUser(null));
    // "Ready" once both have settled, so that the application frame is drawn once, complete
    // with the engine chip, instead of the chip arriving a moment later and moving the header.
    void Promise.all([metaLoaded, sessionLoaded]).finally(() => !cancelled && setStatus("ready"));
    // Any request that comes back 401 (an expired session) signs the user out locally.
    onUnauthorized(() => setUser(null));
    return () => {
      cancelled = true;
      onUnauthorized(null);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const signedIn = await api.login(email, password);
    setSignedOut(false);
    setUser(signedIn);
    return signedIn;
  }, []);

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setSignedOut(true);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ status, user, signedOut, meta, login, logout }),
    [status, user, signedOut, meta, login, logout],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}
