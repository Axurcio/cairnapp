import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, api, setCsrfToken, setUnauthorizedHandler } from "../api/client";
import type { Account, Role } from "../api/types";

type AuthState =
  | { status: "loading" }
  | { status: "signed-out"; reason?: string }
  | { status: "signed-in"; account: Account };

interface AuthContextValue {
  state: AuthState;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const signedOut = useCallback((reason?: string) => {
    setCsrfToken(null);
    setState({ status: "signed-out", reason });
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => signedOut("Your session has ended. Please sign in again."));
    // Restore an existing session (the cookie survives page reloads).
    api
      .session()
      .then((session) => {
        setCsrfToken(session.csrf_token);
        setState({ status: "signed-in", account: session.account });
      })
      .catch(() => signedOut());
    return () => setUnauthorizedHandler(null);
  }, [signedOut]);

  const login = useCallback(async (email: string, password: string) => {
    const session = await api.login(email, password);
    setCsrfToken(session.csrf_token);
    setState({ status: "signed-in", account: session.account });
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (err) {
      // Already signed out on the server; still clear the page state.
      if (!(err instanceof ApiError)) throw err;
    }
    signedOut();
  }, [signedOut]);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** The signed-in account. Only use below <RequireAuth>. */
export function useAccount(): Account {
  const { state } = useAuth();
  if (state.status !== "signed-in") throw new Error("useAccount requires a signed-in user");
  return state.account;
}

export function hasRole(account: Account, role: Role): boolean {
  return account.roles.includes(role);
}
