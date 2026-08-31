import { motion } from "framer-motion";
import { Boxes, Cloud, Database, Cpu, Server, Zap } from "lucide-react";
import { useState } from "react";
import { Reveal, Section } from "@/components/site/Section";
import { AdkMark, GeminiMark, GoogleCloudMark } from "@/components/site/GoogleMarks";

const LAYERS = [
  {
    id: "runtime",
    icon: Cloud,
    mark: "cloud" as const,
    name: "FastAPI on Google Cloud Run",
    line: "Containerized service · Google Cloud Run",
    detail:
      "The agent runtime ships with a Dockerfile and runs as a standard FastAPI/uvicorn ASGI service. APScheduler jobs for scheduled agent runs share the same event loop as the API.",
  },
  {
    id: "model",
    icon: Cpu,
    mark: "gemini" as const,
    name: "Gemini 3.7 Flash",
    line: "Gemini API · reasoning, tools, Gemini voice",
    detail:
      "Low-latency reasoning with function calling drives every agent turn. Structured output schemas keep proposals machine-verifiable before they ever reach a manager.",
  },
  {
    id: "adk",
    icon: Boxes,
    mark: "google" as const,
    name: "Google ADK",
    line: "Agent orchestration, tool registry, session state",
    detail:
      "The Agent Development Kit wires the conductor to the seven specialists, enforces the KYA tool registry, and carries session state and traces across delegated turns.",
  },
  {
    id: "api",
    icon: Server,
    name: "FastAPI · MaSoVa Core API",
    line: "Scoped AGENT_TOKEN + JWT · policy gate",
    detail:
      "The only path to store data. Tokens issued to agents carry read/propose scopes exclusively; execute scopes are reserved for human sessions authenticated with a manager JWT.",
  },
  {
    id: "data",
    icon: Database,
    name: "SQLite + hash-chained JSONL",
    line: "Demo store telemetry · append-only audit ledger",
    detail:
      "The hackathon demo backend is SQLite-backed. Every agent run and every manager decision is additionally appended to a SHA-256 hash-chained JSONL ledger — edit any past line and every hash after it stops verifying.",
  },
  {
    id: "cache",
    icon: Zap,
    name: "Redis",
    line: "Session storage",
    detail:
      "Backs RedisSessionService for ADK conversation/session state, with an in-memory fallback if Redis is unreachable — so a local demo run never hard-depends on it.",
  },
];

export function Architecture() {
  const [active, setActive] = useState(LAYERS[0]!.id);
  const current = LAYERS.find((l) => l.id === active)!;

  return (
    <Section
      id="architecture"
      eyebrow="Hackathon build"
      title="Architecture & tech stack"
      description="Fortified Enterprise Fleet track: an ADK-orchestrated agent mesh, gated by a policy-enforcing FastAPI core and an append-only cryptographic ledger."
      photo="kitchen"
    >
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-3">
          {LAYERS.map((l, i) => (
            <Reveal key={l.id} delay={i * 0.05}>
              <button
                onClick={() => setActive(l.id)}
                className={`surface relative w-full overflow-hidden rounded-xl border p-4 text-left transition-colors ${
                  active === l.id ? "border-primary/60" : "border-border/70 hover:border-border"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-lg bg-white/5 text-primary">
                    {"mark" in l && l.mark === "gemini" ? (
                      <GeminiMark className="size-4.5" />
                    ) : "mark" in l && l.mark === "cloud" ? (
                      <GoogleCloudMark className="size-4.5" />
                    ) : "mark" in l && l.mark === "google" ? (
                      <AdkMark className="size-4.5" />
                    ) : (
                      <l.icon className="size-4" />
                    )}
                  </span>
                  <div>
                    <p className="text-sm font-semibold">{l.name}</p>
                    <p className="text-xs text-muted-foreground">{l.line}</p>
                  </div>
                </div>
              </button>
            </Reveal>
          ))}
        </div>

        <div className="surface flex flex-col justify-between rounded-2xl border border-border/70 p-6">
          <div>
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-white/5 text-primary">
                {"mark" in current && current.mark === "gemini" ? (
                  <GeminiMark className="size-5" />
                ) : "mark" in current && current.mark === "cloud" ? (
                  <GoogleCloudMark className="size-5" />
                ) : "mark" in current && current.mark === "google" ? (
                  <AdkMark className="size-5" />
                ) : (
                  <current.icon className="size-5" />
                )}
              </span>
              <div>
                <h4 className="text-lg font-semibold">{current.name}</h4>
                <p className="text-xs text-muted-foreground">{current.line}</p>
              </div>
            </div>
            <p className="mt-5 text-sm leading-relaxed text-muted-foreground">{current.detail}</p>
          </div>
          <div className="mt-8 rounded-xl border border-border/60 bg-background/50 p-4 font-mono text-[11px] text-muted-foreground">
            <span className="text-emerald">Security Status:</span> Enforced at Gateway
          </div>
        </div>
      </div>
    </Section>
  );
}
