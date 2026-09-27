"use client";
import { useEffect, useRef, useState } from "react";

type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
};
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

export function useVoice(onTranscript: (text: string) => void) {
  const [state, setState] = useState<"Idle" | "Listening" | "Processing" | "Speaking" | "Error">(
    "Idle",
  );
  const [error, setError] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const keepListening = useRef(false);
  const restartTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const utterance = useRef<SpeechSynthesisUtterance | null>(null);
  useEffect(
    () => () => {
      keepListening.current = false;
      if (restartTimer.current) clearTimeout(restartTimer.current);
      if (recognition.current) {
        recognition.current.onresult =
          recognition.current.onerror =
          recognition.current.onend =
            null;
        recognition.current.abort();
      }
      if (utterance.current) {
        utterance.current.onend = utterance.current.onerror = null;
        window.speechSynthesis?.cancel();
      }
    },
    [],
  );
  function cancel() {
    keepListening.current = false;
    if (restartTimer.current) clearTimeout(restartTimer.current);
    restartTimer.current = null;
    const current = recognition.current;
    recognition.current = null;
    if (current) {
      current.onresult = current.onerror = current.onend = null;
      current.abort();
    }
    if (utterance.current) {
      utterance.current.onend = utterance.current.onerror = null;
      utterance.current = null;
      window.speechSynthesis?.cancel();
    }
    setState("Idle");
    setError("");
  }
  function fail(message: string) {
    cancel();
    setError(message);
    setState("Error");
  }
  function start() {
    cancel();
    const browser = window as SpeechWindow;
    const Constructor = browser.SpeechRecognition || browser.webkitSpeechRecognition;
    if (!Constructor) {
      fail("Speech recognition is unsupported in this browser. You can still type.");
      return;
    }
    keepListening.current = true;
    let completedTranscript = "";
    function beginSession() {
      restartTimer.current = null;
      if (!keepListening.current || !Constructor) return;
      try {
        const current = new Constructor();
        let sessionTranscript = "";
        recognition.current = current;
        current.lang = navigator.language || "en-US";
        current.interimResults = true;
        current.continuous = true;
        current.onresult = (event) => {
          if (recognition.current !== current) return;
          // Results are cumulative within a session, but reset after a reconnect.
          sessionTranscript = Array.from(event.results, (result) => result[0].transcript)
            .join(" ")
            .trim();
          const transcript = [completedTranscript, sessionTranscript].filter(Boolean).join(" ");
          if (transcript) onTranscript(transcript.slice(0, 4000));
        };
        current.onerror = (event) => {
          if (recognition.current !== current) return;
          // Silence is recoverable; the browser's following end event reconnects.
          if (event.error === "no-speech") return;
          fail(
            event.error === "not-allowed" || event.error === "service-not-allowed"
              ? "Microphone permission denied. Allow microphone access or keep typing."
              : "Speech recognition failed. Please try again or type your message.",
          );
        };
        current.onend = () => {
          if (recognition.current !== current) return;
          recognition.current = null;
          current.onresult = current.onerror = current.onend = null;
          completedTranscript = [completedTranscript, sessionTranscript].filter(Boolean).join(" ");
          if (keepListening.current) {
            // Some browsers close even continuous sessions. Keep the user's
            // listening intent, and retain text across the next session.
            restartTimer.current = setTimeout(beginSession, 300);
          } else {
            setState("Idle");
          }
        };
        setState("Listening");
        current.start();
      } catch {
        fail("Could not start the microphone. You can still type.");
      }
    }
    beginSession();
  }
  function stop() {
    keepListening.current = false;
    if (restartTimer.current) clearTimeout(restartTimer.current);
    restartTimer.current = null;
    try {
      if (recognition.current) {
        setState("Processing");
        recognition.current.stop();
      } else {
        setState("Idle");
      }
    } catch {
      fail("Could not finish speech recognition. Please type your message.");
    }
  }

  function speak(text: string) {
    cancel();
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
      fail("Speech playback is unavailable. The response is available as text.");
      return;
    }
    try {
      const speech = new SpeechSynthesisUtterance(text);
      utterance.current = speech;
      speech.onend = () => {
        setState("Idle");
        utterance.current = null;
      };
      speech.onerror = () => fail("Speech playback failed. The response is available as text.");
      setState("Speaking");
      window.speechSynthesis.speak(speech);
    } catch {
      fail("Speech playback failed. The response is available as text.");
    }
  }
  return { state, error, start, stop, cancel, speak };
}
