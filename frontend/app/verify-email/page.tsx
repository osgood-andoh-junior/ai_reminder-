"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/provider";
import { api } from "@/lib/api";

export default function VerifyEmail() {
  const { user, refresh } = useAuth();
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setToken(new URLSearchParams(window.location.hash.slice(1)).get("token") || "");
    window.history.replaceState(null, "", window.location.pathname);
  }, []);
  async function confirm() {
    setBusy(true);
    try {
      setMessage((await api.confirmVerification(token)).message);
      setToken("");
      await refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-panel">
        <h1>Verify your Xenon email</h1>
        <p>Confirm this address for your signed-in account.</p>
        {!user && (
          <p>
            <Link href="/login">Sign in</Link>, then reopen the link from your verification email.
          </p>
        )}
        <button disabled={busy || !token || !user} onClick={confirm}>
          Verify email
        </button>
        {message && <p role="status">{message}</p>}
        <Link href="/settings">Open Settings</Link>
      </section>
    </main>
  );
}
