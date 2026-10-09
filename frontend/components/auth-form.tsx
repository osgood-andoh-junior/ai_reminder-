"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "./provider";
import { ErrorBox } from "./ui";
import { XenonMark } from "./xenon-mark";
export function AuthForm({ register = false }: { register?: boolean }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { refresh } = useAuth();
  const router = useRouter();
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      const result = await (register ? api.register(data) : api.login(data));
      await refresh();
      if (register) {
        window.sessionStorage.setItem(
          "verification-message",
          result.verification_message || "Verify your email in Settings to receive reminders.",
        );
        router.push("/settings");
      } else router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-panel">
        <div>
          <Link className="brand" href="/login">
            <XenonMark size={32} />
            Xenon
          </Link>
          <p className="auth-tagline">Make time for what matters.</p>
          <h2>{register ? "Make room for a better day." : "Welcome back."}</h2>
          <p>
            {register ? "Create your account to start planning." : "Sign in to your workspace."}
          </p>
          <form onSubmit={submit}>
            {register && (
              <label>
                Your name
                <input
                  name="name"
                  autoComplete="name"
                  required
                  maxLength={100}
                  placeholder="How should we call you?"
                />
              </label>
            )}
            <label>
              Email address
              <input
                name="email"
                type="email"
                autoComplete="email"
                required
                placeholder="you@example.com"
              />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                minLength={register ? 12 : 1}
                maxLength={128}
                required
                placeholder={register ? "At least 12 characters" : "Your password"}
              />
            </label>
            <ErrorBox message={error} />
            <button disabled={busy} className="wide">
              {busy ? "Please wait…" : register ? "Create account" : "Sign in"}
              <ArrowRight size={18} />
            </button>
          </form>
          <p className="auth-switch">
            {register ? "Already have an account?" : "New to Xenon?"}{" "}
            <Link href={register ? "/login" : "/register"}>
              {register ? "Sign in" : "Create an account"}
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
