import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { clearSentryUser, setSentryUser } from "@/instrument";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const applyUser = useCallback((u) => {
    setUser(u);
    if (u) {
      setSentryUser(u);
    } else {
      clearSentryUser();
    }
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      applyUser(data);
    } catch {
      applyUser(null);
    } finally {
      setLoading(false);
    }
  }, [applyUser]);

  useEffect(() => {
    // CRITICAL: if returning from OAuth callback, skip /me. AuthCallback will set the session.
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    checkAuth();
  }, [checkAuth]);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    applyUser(null);
    window.location.href = "/";
  }, [applyUser]);

  return (
    <AuthContext.Provider value={{ user, setUser: applyUser, loading, refresh: checkAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
