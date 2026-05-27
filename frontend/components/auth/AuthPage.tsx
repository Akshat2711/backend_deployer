"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";

import { getMe, login, signup } from "@/lib/api";
import { apiBase, tokenStorageKey } from "@/lib/config";
import { getErrorMessage } from "@/lib/errors";

export function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");

    try {
      if (mode === "signup") {
        await signup(email, password);
      }

      const auth = await login(email, password);
      localStorage.setItem(tokenStorageKey, auth.access_token);
      router.push("/dashboard");
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const savedToken = localStorage.getItem(tokenStorageKey);
    if (!savedToken) return;

    getMe(savedToken)
      .then(() => router.replace("/dashboard"))
      .catch(() => localStorage.removeItem(tokenStorageKey));
  }, [router]);

  return (
    <main className="terminal-root min-h-screen bg-zinc-50 text-zinc-950 dark:bg-zinc-950 dark:text-zinc-50">
      <section className="mx-auto flex min-h-screen w-full max-w-6xl items-center px-6 py-12">
        <div className="grid w-full gap-12 lg:grid-cols-[1fr_440px] lg:items-center">
          
          {/* Left Hero Column */}
          <div className="max-w-2xl">
            {/* Expanded Hero Logo Section */}
            <div className="mb-8 flex flex-col items-start gap-5 sm:flex-row sm:items-center">
              <div className="relative rounded-2xl border border-zinc-200 bg-white p-3 shadow-sm shadow-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-none">
                <div className="absolute inset-0 animate-pulse rounded-2xl bg-cyan-500/5 opacity-50 blur-sm" />
                <Image
                  src="/assets/logo.gif"
                  alt="CloudTurtle Logo"
                  width={120}
                  height={120}
                  priority
                  className="relative z-10 object-contain mix-blend-multiply dark:mix-blend-screen"
                />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
                  <p className="terminal-title text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500 dark:text-zinc-400">
                    CloudTurtle Infrastructure v2.4
                  </p>
                </div>
                <h2 className="mt-1 font-mono text-lg font-bold text-orange-500 dark:text-orange-400">
                  cloudturtle connect --secure
                </h2>
              </div>
            </div>

            {/* Value Proposition */}
            <h1 className="text-4xl font-bold tracking-tight uppercase leading-[1.1] sm:text-5xl lg:text-6xl">
              Next-Gen Backend Hosting Partner.
            </h1>
            
            <p className="mt-6 max-w-xl text-base leading-7 text-zinc-600 dark:text-zinc-400 sm:text-lg">
              CloudTurtle is a high-performance cloud platform engineered for production backend architectures. 
              Deploy containerized applications, provision persistent environments, manage server limits, 
              and spin up continuous deployments directly through our micro-CLI platform.
            </p>

            {/* Platform Feature Badges */}
            <div className="mt-8 grid max-w-2xl gap-3 sm:grid-cols-3">
              {[
                { title: "Isolated Runtimes", desc: "Dedicated resource limits" },
                { title: "FastAPI & Go Native", desc: "Optimized for API scaling" },
                { title: "Real-time Telemetry", desc: "Live terminal log streams" }
              ].map((item) => (
                <div 
                  key={item.title} 
                  className="border-l-2 border-cyan-600 bg-zinc-100/60 p-4 shadow-sm dark:bg-zinc-900/40"
                >
                  <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{item.title}</p>
                  <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{item.desc}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Right Form Column */}
          <form onSubmit={handleAuth} className="terminal-window border border-zinc-200 bg-white p-8 shadow-xl dark:border-zinc-800 dark:bg-zinc-900/50 rounded-xl">
            <div className="mb-6 flex rounded-lg bg-zinc-100 p-1 dark:bg-zinc-800">
              {(["login", "signup"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setMode(item)}
                  className={`h-10 flex-1 rounded-md px-3 text-sm font-semibold capitalize transition ${
                    mode === item 
                      ? "bg-white text-zinc-950 shadow-sm dark:bg-zinc-700 dark:text-white" 
                      : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>

            <label className="block font-mono text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400" htmlFor="email">
              user@cloudturtle:~$ enter email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-2 h-11 w-full rounded-md border border-zinc-300 bg-zinc-50 px-3 text-sm outline-none ring-cyan-500 transition focus:border-transparent focus:ring-2 dark:border-zinc-700 dark:bg-zinc-950"
            />

            <label className="mt-5 block font-mono text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400" htmlFor="password">
              user@cloudturtle:~$ enter token_phrase
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={mode === "signup" ? 8 : undefined}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-2 h-11 w-full rounded-md border border-zinc-300 bg-zinc-50 px-3 text-sm outline-none ring-cyan-500 transition focus:border-transparent focus:ring-2 dark:border-zinc-700 dark:bg-zinc-950"
            />

            <button
              type="submit"
              disabled={busy}
              className="mt-6 h-11 w-full rounded-md bg-zinc-950 px-4 text-sm font-semibold text-white transition hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-950 dark:hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Authorizing node..." : mode === "signup" ? "Initialize provisioning" : "Establish session"}
            </button>

            {message ? (
              <div className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-600 border border-red-100 dark:bg-red-950/30 dark:text-red-400 dark:border-red-900/30">
                {message}
              </div>
            ) : null}
            
            <div className="mt-6 border-t border-zinc-100 pt-4 dark:border-zinc-800">
              <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
                Remote Edge API: {apiBase}
              </p>
            </div>
          </form>
          
        </div>
      </section>
    </main>
  );
}