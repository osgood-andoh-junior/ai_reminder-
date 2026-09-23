"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { User, Preferences } from "@/lib/types";
type Context = {
  user: User | null;
  preferences: Preferences | null;
  loading: boolean;
  refresh: () => Promise<void>;
};
const Auth = createContext<Context>({
  user: null,
  preferences: null,
  loading: true,
  refresh: async () => {},
});
export const useAuth = () => useContext(Auth);
export function Provider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pathname = usePathname();
  const router = useRouter();
  const refresh = useCallback(async () => {
    setError("");
    try {
      const u = await api.me();
      const p = await api.preferences();
      setUser(u);
      setPreferences(p);
    } catch (e) {
      setUser(null);
      if (!(e instanceof ApiError && e.status === 401)) setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    const expired = () => {
      void refresh();
    };
    window.addEventListener("auth-expired", expired);
    return () => window.removeEventListener("auth-expired", expired);
  }, [refresh]);
  const publicPage = ["/login", "/register"].includes(pathname);
  useEffect(() => {
    if (!loading && !user && !publicPage && !error) router.replace("/login");
  }, [loading, user, publicPage, router, error]);
  if (error && !publicPage)
    return (
      <main className="connection-error">
        <h1>Let’s reconnect</h1>
        <p role="alert">{error}</p>
        <button onClick={refresh}>Try again</button>
      </main>
    );
  return (
    <Auth.Provider value={{ user, preferences, loading, refresh }}>
      {publicPage || user ? (
        children
      ) : (
        <main className="connection-error">
          <span className="spinner" /> Opening your workspace…
        </main>
      )}
    </Auth.Provider>
  );
}
