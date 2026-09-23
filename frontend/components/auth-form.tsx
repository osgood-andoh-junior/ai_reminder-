"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, CalendarClock, Sparkles, Check } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "./provider";
import { ErrorBox } from "./ui";
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
      await (register ? api.register(data) : api.login(data));
      await refresh();
      router.push("/assistant");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-story">
        <Link className="brand" href="/login">
          <span className="brand-icon">t</span>tempo.
        </Link>
        <div>
          <span className="eyebrow">SPACE FOR WHAT MATTERS</span>
          <h1>
            Your day.
            <br />
            With a little
            <br />
            <em>more possibility.</em>
          </h1>
          <p>
            A thoughtful plan for your tasks, your time,
            <br />
            and the way you work best.
          </p>
          <div className="auth-features">
            <span>
              <CalendarClock />
              Plans built around your calendar
            </span>
            <span>
              <Sparkles />A personal scheduling assistant
            </span>
            <span>
              <Check />
              You stay in control of every change
            </span>
          </div>
        </div>
        <small>Personalized AI Agent for Intelligent Scheduling</small>
      </section>
      <section className="auth-panel">
        <div>
          <span className="eyebrow">YOUR PERSONAL WORKSPACE</span>
          <h2>{register ? "Make room for a better day." : "Welcome back."}</h2>
          <p>
            {register
              ? "Create your account to start planning."
              : "Your next thoughtful plan starts here."}
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
            {register ? "Already have an account?" : "New to Tempo?"}{" "}
            <Link href={register ? "/login" : "/register"}>
              {register ? "Sign in" : "Create an account"}
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
