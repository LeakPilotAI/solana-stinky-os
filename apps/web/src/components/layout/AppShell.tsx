"use client";

import { useEffect, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { CommandPalette } from "./CommandPalette";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const path = usePathname();

  useEffect(() => {
    // Warm common routes once
    const routes = [
      "/command-center",
      "/runners",
      "/investigations",
      "/wallets",
      "/entities",
      "/alerts",
      "/patterns",
      "/recipes",
      "/observations",
      "/unknown",
      "/dips",
      "/graph",
      "/smart-money",
      "/health",
    ];
    routes.forEach((r) => {
      try {
        router.prefetch(r);
      } catch {
        /* ignore */
      }
    });
  }, [router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    let pendingKey = false;
    const onKey = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;
      if (e.key === "g" && !pendingKey) {
        pendingKey = true;
        setTimeout(() => {
          pendingKey = false;
        }, 600);
        return;
      }
      if (!pendingKey) return;
      pendingKey = false;
      const map: Record<string, string> = {
        c: "/command-center",
        r: "/runners",
        v: "/investigations",
        w: "/wallets",
        e: "/entities",
        a: "/alerts",
        s: "/smart-money",
        p: "/patterns",
        y: "/recipes",
        o: "/observations",
        u: "/unknown",
        d: "/dips",
        g: "/graph",
        t: "/time-machine",
        q: "/research",
        b: "/backtest",
        h: "/health",
      };
      const href = map[e.key.toLowerCase()];
      if (href) {
        startTransition(() => router.push(href));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-terminal-bg">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative">
          <TopBar onOpenSearch={() => setSearchOpen(true)} />
          {(pending || false) && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 overflow-hidden">
              <div className="h-full w-1/3 animate-pulse bg-terminal-accent" />
            </div>
          )}
        </div>
        <main
          key={path}
          className="min-h-0 flex-1 overflow-auto transition-opacity duration-100"
        >
          {children}
        </main>
      </div>
      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
