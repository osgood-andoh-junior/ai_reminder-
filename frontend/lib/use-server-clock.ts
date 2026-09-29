"use client";
import { useEffect, useState } from "react";
import { api } from "./api";

// Advance a server sample with elapsed monotonic time, never the device's calendar clock.
export function projectedServerTime(utc: string, sampledAt: number, monotonicNow: number) {
  return Date.parse(utc) + Math.max(0, monotonicNow - sampledAt);
}

export function useServerClock(userId: number | undefined, zone: string | undefined) {
  const [now, setNow] = useState<number | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let sequence = 0;
    let sample: { utc: string; at: number } | null = null;
    setNow(null);
    setError("");
    if (!userId || !zone) return;
    const sync = async () => {
      const request = ++sequence;
      try {
        const value = await api.time();
        if (!active || request !== sequence) return;
        sample = { utc: value.utc_now, at: performance.now() };
        setNow(Date.parse(sample.utc));
        setError("");
      } catch {
        if (active && request === sequence)
          setError("Couldn’t sync the current time with Xenon. Check your connection.");
      }
    };
    const visible = () => {
      if (document.visibilityState === "visible") void sync();
    };
    void sync();
    const refresh = setInterval(() => void sync(), 60000);
    const tick = setInterval(() => {
      if (sample) setNow(projectedServerTime(sample.utc, sample.at, performance.now()));
    }, 1000);
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    return () => {
      active = false;
      clearInterval(refresh);
      clearInterval(tick);
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [userId, zone]);
  return { now, clockError: error };
}
