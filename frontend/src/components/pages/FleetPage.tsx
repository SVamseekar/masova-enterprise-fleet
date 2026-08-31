import { motion } from "framer-motion";
import {
  ArrowRight,
  BadgeCheck,
  Fingerprint,
  Gauge,
  Github,
  ShieldCheck,
  Terminal,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AgentsGrid } from "@/components/fleet/AgentsGrid";
import { Architecture } from "@/components/fleet/Architecture";
import { CopilotPlayground } from "@/components/fleet/CopilotPlayground";
import { GovernanceLab } from "@/components/fleet/GovernanceLab";
import { GovernanceMatrix } from "@/components/fleet/GovernanceMatrix";
import { Reveal, Section } from "@/components/site/Section";
import { AdkMark, BrandChip, GeminiMark, GoogleCloudMark } from "@/components/site/GoogleMarks";
import { CONSOLE_PATH } from "@/lib/console";

const STATS = [
  { icon: Users, value: "7 + 1", label: "Specialists + conductor" },
  { icon: Gauge, value: "0", label: "Execute-tier tools allowlisted" },
  { icon: Fingerprint, value: "SHA-256", label: "Hash-chained decisions" },
];

const REQUIREMENTS = [
  {
    mark: "adk" as const,
    tag: "google adk · gemini 3.7 flash",
    title: "Built on Google ADK & Gemini 3.7 Flash",
    body: "Every specialist agent is an ADK agent with declared tools, typed schemas and per-agent scope manifests. Gemini 3.7 Flash handles reasoning, RAG grounding and proposal drafting — including Gemini speech for the copilot.",
  },
  {
    mark: "cloud" as const,
    tag: "google cloud run",
    title: "Containerized, Google Cloud Run-ready",
    body: "The agent runtime ships with a Dockerfile and runs as a standard FastAPI/uvicorn service on Google Cloud Run, writing every run to a tamper-evident SHA-256 hash-chain audit ledger on disk.",
  },
  {
    mark: "gemini" as const,
    tag: "gemini api · voice",
    title: "Gemini API and Gemini voice",
    body: "Manager Copilot answers from the ops manual over the Gemini API. Spoken replies use Gemini speech synthesis — the same Gemini family as the text model, not a third-party voice stack.",
  },
];

const VALUE_CARDS = [
  {
    title: "Zero unauthorized side effects",
    body: "Write scopes never reach the fleet. Purchase orders, price changes and guest messaging are structurally impossible without a manager decision.",
  },
  {
    title: "HITL proposal architecture",
    body: "Every consequential action is a signed draft carrying rationale, confidence and blast radius — reviewed in seconds, not meetings.",
  },
  {
    title: "Real-time operations",
    body: "Forecasts, stock depletion, KDS pacing and guest sentiment stream continuously; proposals appear the moment a threshold moves.",
  },
];

const CRITERIA = [
  {
    weight: "40%",
    title: "Innovation & Operational Utility",
    body: "A working answer to the hardest question in enterprise agents: how do specialists draft work without handing over the keys? Seven specialist agents plus a conversational conductor cover the real daily loop of a multi-store restaurant group — forecasting, purchasing, pricing, churn, reviews, shifts, kitchen coaching.",
    points: [
      "Proposal-first design: analysis can run; consequence waits for a manager",
      "Grounded in real ops artifacts — HACCP SOPs, supplier catalogs, POS history",
      "Measured in manager minutes saved per shift, not tokens generated",
    ],
  },
  {
    weight: "30%",
    title: "Architectural Discipline & Tech Stack",
    body: "ADK agents with explicit tool manifests, scoped short-lived AGENT_TOKENs, a policy hash pinned per release, and a deterministic hash-chained run store. Boundary is enforced at the token, not the prompt.",
    points: [
      "Gemini 3.7 Flash + Google ADK agent runtime, containerized and Cloud Run-ready",
      "Scope manifests denied at the API gateway, not in system instructions",
      "SHA-256 previous_hash linkage makes ledger edits detectable",
    ],
  },
  {
    weight: "30%",
    title: "Demo & Production Readiness",
    body: "Everything is interactive: approve or decline live proposals and watch a new signed block append to the ledger, query the ops manual through the Manager Copilot, and inspect any block's identity and payload signature.",
    points: [
      "Live proposal queue with guardrail, GDPR and supplier constraints",
      "Voice + RAG copilot simulator over the ops manual corpus",
      "Block explorer exposing index, timestamp, agent identity and signature",
    ],
  },
];

export function FleetPage() {
  return (
    <>
      <section className="relative min-h-[92vh] overflow-hidden">
        <div className="absolute inset-0 overflow-hidden" aria-hidden>
          <div className="photo-kitchen ken-burns photo-recess absolute inset-0" />
          <div className="absolute inset-0 bg-gradient-to-r from-background via-background/80 to-background/50" />
          <div className="absolute inset-0 bg-gradient-to-t from-background via-background/35 to-background/55" />
          <div className="film-grain" />
        </div>
        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 py-20 sm:px-6 sm:py-28 lg:grid-cols-[1.05fr_0.95fr] lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-black/30 px-3.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-zinc-200 backdrop-blur">
                <span className="pulse-dot size-1.5 rounded-full bg-emerald" />
                Manager Copilot for multi-store restaurant fleets
              </span>
            </div>

            <h1 className="mt-6 text-4xl font-semibold leading-[1.08] sm:text-5xl lg:text-6xl">
              Every agent proposes.
              <span className="sr-only"> </span>
              <br />
              <span className="text-gradient">Only a manager approves.</span>
            </h1>

            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-zinc-300">
              Seven specialist agents watch demand, stock, pricing, reviews, shifts, and kitchen
              pacing across your stores — and a Manager Copilot answers questions and coordinates
              them from one chat. Nothing writes to your systems, spends money, or messages a guest
              without a manager's sign-off, and every decision is recorded in a tamper-evident log.
            </p>

            <div className="mt-9 flex flex-wrap gap-3">
              <Button asChild size="xl" variant="hero">
                <a href={CONSOLE_PATH}>
                  Open the manager console <ArrowRight className="size-4" />
                </a>
              </Button>
              <Button asChild size="xl" variant="subtle">
                <a href="https://github.com/SVamseekar/masova-enterprise-fleet" target="_blank" rel="noreferrer">
                  <Github className="size-4" /> View source on GitHub
                </a>
              </Button>
            </div>

            <div className="mt-8 flex flex-wrap gap-2">
              <BrandChip mark="gemini" label="Gemini 3.7 Flash" />
              <BrandChip mark="adk" label="Google ADK" />
              <BrandChip mark="cloud" label="Google Cloud Run" />
              <BrandChip mark="gemini" label="Gemini voice" />
            </div>

            <div className="mt-14 grid max-w-2xl grid-cols-3 gap-3">
              {STATS.map((s, i) => (
                <motion.div
                  key={s.label}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 + i * 0.08, ease: [0.16, 1, 0.3, 1] }}
                  className="glass-ticket rounded-xl p-4"
                >
                  <s.icon className="size-4 text-primary" />
                  <p className="mt-3 font-display text-xl font-semibold">{s.value}</p>
                  <p className="text-[11px] text-zinc-400">{s.label}</p>
                </motion.div>
              ))}
            </div>
          </motion.div>

          <motion.aside
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="relative hidden overflow-hidden rounded-2xl lg:block"
          >
            <div className="glass-ticket relative overflow-hidden rounded-2xl">
              <div className="photo-cellar absolute inset-0 opacity-35" aria-hidden />
              <div className="absolute inset-0 bg-black/55" aria-hidden />
              <div className="relative p-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-400">
                      Draft purchase order · Store DOM011
                    </p>
                    <p className="mt-1 font-display text-lg font-semibold">Restock — Oberkampf</p>
                  </div>
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald/15 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-emerald">
                    <span className="pulse-dot size-1.5 rounded-full bg-emerald" />
                    Awaiting review
                  </span>
                </div>
                <div className="mt-5 space-y-2 text-sm">
                  {[
                    ["Mozzarella, shredded", "18 kg"],
                    ["Tomato base, San Marzano", "12 L"],
                    ["00 flour, Caputo", "25 kg"],
                  ].map(([item, qty]) => (
                    <div
                      key={item}
                      className="flex items-center justify-between rounded-lg border border-white/8 bg-black/35 px-3 py-2.5"
                    >
                      <span>{item}</span>
                      <span className="font-mono text-zinc-300">{qty}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-5 flex items-center justify-between border-t border-dashed border-white/15 pt-4">
                  <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-400">
                    Status · pending — not sent to supplier
                  </span>
                  <Button asChild size="sm" variant="subtle">
                    <a href="#queue">Review</a>
                  </Button>
                </div>
              </div>
            </div>
          </motion.aside>
        </div>
      </section>

      <Section
        id="overview"
        eyebrow="How it's governed"
        title={
          <>
            Two kinds of work, <span className="text-gradient">one hard boundary.</span>
          </>
        }
        description="Agents run continuously on the work that carries no risk. Anything that touches money, inventory, pricing, or a guest waits for a person."
        photo="ops"
      >
        <div className="grid gap-4 md:grid-cols-3">
          {VALUE_CARDS.map((c, i) => (
            <Reveal key={c.title} delay={i * 0.08}>
              <div className="surface h-full rounded-2xl border border-border/70 p-6">
                <span className="grid size-9 place-items-center rounded-lg bg-primary/15 font-mono text-sm text-primary">
                  0{i + 1}
                </span>
                <h3 className="mt-4 text-lg font-semibold">{c.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      <GovernanceMatrix />
      <AgentsGrid />
      <GovernanceLab />

      <Section
        id="stack"
        eyebrow="What it is built on"
        title={
          <>
            Gemini, ADK, and a <span className="text-gradient">hard write boundary.</span>
          </>
        }
        description="The stack that actually runs: Google ADK agents, Gemini for reasoning, FastAPI on Google Cloud Run, and a SHA-256 hash chain for every decision."
        photo="command"
      >
        <div className="grid gap-4 md:grid-cols-3">
          {REQUIREMENTS.map((r, i) => (
            <Reveal key={r.title} delay={i * 0.08}>
              <div className="surface h-full rounded-2xl border border-border/70 p-6">
                <span className="grid size-9 place-items-center rounded-lg bg-white/5">
                  {r.mark === "gemini" ? (
                    <GeminiMark className="size-5" />
                  ) : r.mark === "cloud" ? (
                    <GoogleCloudMark className="size-5" />
                  ) : (
                    <AdkMark className="size-5" />
                  )}
                </span>
                <p className="mt-4 font-mono text-[11px] text-muted-foreground">{r.tag}</p>
                <h3 className="mt-1.5 text-lg font-semibold">{r.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{r.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      <Architecture />
      <CopilotPlayground />

      <Section
        id="criteria"
        eyebrow="What to look for"
        title="How to evaluate the system"
        description="Three things to check — in the console, not only on this page."
        photo="supply"
      >
        <div className="grid gap-5 lg:grid-cols-3">
          {CRITERIA.map((c, i) => (
            <Reveal key={c.title} delay={i * 0.08}>
              <div className="surface flex h-full flex-col rounded-2xl border border-border/70 p-7">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-lg font-semibold">{c.title}</h3>
                  <span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 font-mono text-xs text-primary">
                    {c.weight}
                  </span>
                </div>
                <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                  <motion.span
                    initial={{ width: 0 }}
                    whileInView={{ width: c.weight }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                    className="block h-full rounded-full bg-[image:var(--gradient-primary)]"
                  />
                </div>
                <p className="mt-5 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
                <ul className="mt-5 space-y-2.5">
                  {c.points.map((p) => (
                    <li key={p} className="flex gap-2 text-sm text-muted-foreground">
                      <BadgeCheck className="mt-0.5 size-4 shrink-0 text-emerald" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      <Section photo="kitchen">
        <Reveal>
          <div className="surface relative overflow-hidden rounded-3xl border border-primary/25 p-10 text-center">
            <div className="hero-glow absolute inset-0 opacity-70" aria-hidden />
            <div className="relative">
              <h2 className="text-3xl font-semibold sm:text-4xl">
                Open the console when you want to try it
              </h2>
              <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
                Review a live proposal, record the decision, and watch a new block append to the
                hash chain. Agents can draft; they cannot write on their own.
              </p>
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                <Button asChild size="lg" variant="hero">
                  <a href={CONSOLE_PATH}>
                    <Terminal className="size-4" /> Open the manager console{" "}
                    <ArrowRight className="size-4" />
                  </a>
                </Button>
                <Button asChild size="lg" variant="subtle">
                  <a href="https://github.com/SVamseekar/masova-enterprise-fleet" target="_blank" rel="noreferrer">
                    <Github className="size-4" /> Source on GitHub
                  </a>
                </Button>
              </div>
            </div>
          </div>
        </Reveal>
      </Section>
    </>
  );
}
