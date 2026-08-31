import { AnimatePresence, motion } from "framer-motion";
import {
  BadgeCheck,
  Check,
  ChevronDown,
  Fingerprint,
  Link2,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PROPOSAL_SEEDS, type ProposalSeed } from "@/lib/masova-data";
import { Reveal, Section } from "@/components/site/Section";

async function sha256Hex(input: string) {
  const bytes = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

type Block = {
  index: number;
  agent: string;
  store: string;
  action: string;
  decision: "APPROVED" | "DECLINED" | "GENESIS";
  timestamp: string;
  payload: string;
  prevHash: string;
  hash: string;
};

const GENESIS_PREV = "0".repeat(64);

async function makeBlock(
  index: number,
  prevHash: string,
  data: Omit<Block, "index" | "prevHash" | "hash">
): Promise<Block> {
  const payloadString = `${index}|${prevHash}|${data.agent}|${data.store}|${data.action}|${data.decision}|${data.timestamp}`;
  return { ...data, index, prevHash, hash: await sha256Hex(payloadString) };
}

const GENESIS_DATA = {
  agent: "system.bootstrap",
  store: "FLEET",
  action: "Audit chain initialized · KYA policy v2.4 loaded",
  decision: "GENESIS" as const,
  timestamp: "2026-08-30T04:00:12Z",
  payload: "policy_hash=kya-v2.4 · agents=7+1 · execute_tier=blocked",
};

const tierStyles: Record<string, string> = {
  Low: "bg-emerald/15 text-emerald border-emerald/30",
  Medium: "bg-primary/15 text-primary border-primary/30",
};

export function GovernanceLab() {
  const [queue, setQueue] = useState<ProposalSeed[]>(PROPOSAL_SEEDS);
  const [expanded, setExpanded] = useState<string | null>(PROPOSAL_SEEDS[0]!.id);
  const [chain, setChain] = useState<Block[]>([]);
  const [openBlock, setOpenBlock] = useState<number | null>(0);
  const [stats, setStats] = useState({ approved: 0, declined: 0, valueUnlocked: 0 });
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  useEffect(() => {
    makeBlock(0, GENESIS_PREV, GENESIS_DATA).then((genesis) => setChain([genesis]));
  }, []);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3500);
  };

  const decide = async (p: ProposalSeed, decision: "APPROVED" | "DECLINED") => {
    setQueue((q) => q.filter((x) => x.id !== p.id));
    const prev = chain[chain.length - 1];
    if (!prev) return;
    const block = await makeBlock(prev.index + 1, prev.hash, {
      agent: p.agentId,
      store: p.store,
      action: `${p.id} · ${p.title}`,
      decision,
      timestamp: new Date().toISOString(),
      payload: `confidence=${p.confidence} · risk=${p.risk} · approver=gm.dom011 · tier=propose`,
    });
    setChain((c) => [...c, block]);
    setStats((s) => ({
      approved: s.approved + (decision === "APPROVED" ? 1 : 0),
      declined: s.declined + (decision === "DECLINED" ? 1 : 0),
      valueUnlocked: s.valueUnlocked + (decision === "APPROVED" ? Math.round(p.confidence * 300) : 0),
    }));
    if (decision === "APPROVED") {
      showToast(`✓ ${p.id} approved and signed into block #${block.index} · ${p.agent}`);
    } else {
      showToast(`✗ ${p.id} declined · Record hashed into audit chain.`);
    }
  };

  const reset = async () => {
    setQueue(PROPOSAL_SEEDS);
    setChain([await makeBlock(0, GENESIS_PREV, GENESIS_DATA)]);
    setStats({ approved: 0, declined: 0, valueUnlocked: 0 });
    setExpanded(PROPOSAL_SEEDS[0]!.id);
    showToast("Simulation reset: Queue restored and chain rewound to genesis.");
  };

  return (
    <>
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl border border-primary/40 bg-card p-4 text-sm font-medium shadow-2xl backdrop-blur-md">
          {toastMsg}
        </div>
      )}

      <Section
        id="queue"
        eyebrow="Human-in-the-loop"
        title={
          <>
            Live proposal queue — <span className="text-gradient">store Paris DOM011</span>
          </>
        }
        description="Every side-effecting action arrives here as a signed draft. Approve or decline; the fleet never writes without you, and every decision is immediately hashed into the audit chain below."
        photo="command"
      >
        <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
          <div className="space-y-4">
            <AnimatePresence mode="popLayout">
              {queue.map((p) => (
                <motion.article
                  key={p.id}
                  layout
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -40, scale: 0.97 }}
                  transition={{ type: "spring", stiffness: 260, damping: 28 }}
                  className="surface rounded-2xl border border-border/70 p-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span className="font-mono text-primary font-bold">{p.id}</span>
                        <span>·</span>
                        <span>{p.agent}</span>
                        <span>·</span>
                        <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px]">
                          {p.store}
                        </span>
                      </div>
                      <h3 className="mt-1.5 text-base font-semibold">{p.title}</h3>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${tierStyles[p.risk]}`}>
                        Risk · {p.risk}
                      </span>
                      <span className="rounded-full border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {Math.round(p.confidence * 100)}% conf
                      </span>
                    </div>
                  </div>

                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{p.rationale}</p>

                  {p.note && (
                    <p className="mt-2.5 flex items-center gap-2 text-xs text-primary">
                      <ShieldAlert className="size-3.5" />
                      {p.note}
                    </p>
                  )}

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {p.badges.map((b) => (
                      <span
                        key={b}
                        className="rounded-md border border-border/80 bg-background/60 px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
                      >
                        {b}
                      </span>
                    ))}
                  </div>

                  <div className="mt-4 border-t border-border/60 pt-3">
                    <button
                      onClick={() => setExpanded(expanded === p.id ? null : p.id)}
                      className="flex w-full items-center justify-between text-xs text-muted-foreground hover:text-foreground"
                    >
                      <span>Inspection details</span>
                      <ChevronDown
                        className={`size-3.5 transition-transform ${expanded === p.id ? "rotate-180" : ""}`}
                      />
                    </button>

                    {expanded === p.id && (
                      <motion.dl
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        className="mt-3 grid grid-cols-2 gap-2 text-xs"
                      >
                        {p.detail.map((d) => (
                          <div key={d.label} className="rounded-lg border border-border/50 bg-background/40 p-2">
                            <dt className="font-mono text-[10px] text-muted-foreground">{d.label}</dt>
                            <dd className="mt-0.5 font-medium">{d.value}</dd>
                          </div>
                        ))}
                      </motion.dl>
                    )}
                  </div>

                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
                    <span className="font-mono text-xs text-emerald">{p.impact}</span>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => decide(p, "DECLINED")}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <X className="mr-1 size-3.5" /> Decline
                      </Button>
                      <Button size="sm" variant="hero" onClick={() => decide(p, "APPROVED")}>
                        <Check className="mr-1 size-3.5" /> Approve &amp; apply
                      </Button>
                    </div>
                  </div>
                </motion.article>
              ))}
            </AnimatePresence>

            {queue.length === 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                className="surface flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/80 p-12 text-center"
              >
                <div className="grid size-12 place-items-center rounded-full bg-emerald/15 text-emerald">
                  <BadgeCheck className="size-6" />
                </div>
                <h3 className="mt-4 text-lg font-semibold">Queue clear · zero pending drafts</h3>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  All proposals resolved. Decisions appended to the tamper-evident SHA-256 chain.
                </p>
                <Button size="sm" variant="subtle" onClick={reset} className="mt-5">
                  Reset simulation queue
                </Button>
              </motion.div>
            )}
          </div>

          <div className="space-y-4">
            <div className="surface rounded-2xl border border-border/70 p-5">
              <h4 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Session governance summary
              </h4>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-border/60 bg-background/50 p-3">
                  <p className="font-mono text-2xl font-bold text-emerald">{stats.approved}</p>
                  <p className="text-[11px] text-muted-foreground">Approved &amp; applied</p>
                </div>
                <div className="rounded-xl border border-border/60 bg-background/50 p-3">
                  <p className="font-mono text-2xl font-bold text-muted-foreground">{stats.declined}</p>
                  <p className="text-[11px] text-muted-foreground">Declined</p>
                </div>
              </div>
              <div className="mt-4 rounded-xl border border-primary/30 bg-primary/10 p-3.5">
                <p className="flex items-center gap-1.5 text-xs font-medium text-primary">
                  <Sparkles className="size-3.5" /> Value unlocked (simulated)
                </p>
                <p className="mt-1 font-display text-2xl font-bold text-primary">
                  +€{stats.valueUnlocked.toLocaleString()}
                </p>
              </div>
            </div>

            <div className="surface rounded-2xl border border-border/70 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Hard safety invariant
              </p>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                The fleet possesses <strong>zero execute scopes</strong>. Write routes on the MaSoVa
                Core API are rejected at the gateway unless authenticated by a human manager session.
              </p>
            </div>
          </div>
        </div>
      </Section>

      <Section
        id="audit"
        eyebrow="Audit & integrity"
        title="Tamper-evident SHA-256 hash-chain ledger"
        description="Every approved or declined proposal appends a block linking previous_hash, agent identity, store code and signature. Tampering with any historical block invalidates every subsequent hash."
        photo="cellar"
      >
        <div className="surface rounded-2xl border border-border/70 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
            <div className="flex items-center gap-2">
              <Fingerprint className="size-5 text-primary" />
              <span className="font-mono text-sm font-semibold">Ledger depth: {chain.length} blocks</span>
            </div>
            <span className="font-mono text-xs text-emerald">Chain integrity · Verified</span>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {chain.map((b) => (
              <button
                key={b.index}
                onClick={() => setOpenBlock(openBlock === b.index ? null : b.index)}
                className={`surface relative rounded-xl border p-4 text-left transition-colors ${
                  openBlock === b.index ? "border-primary" : "border-border/70 hover:border-border"
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono font-bold text-primary">Block #{b.index}</span>
                  <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {b.decision}
                  </span>
                </div>
                <p className="mt-2 line-clamp-1 text-sm font-medium">{b.action}</p>
                <div className="mt-3 space-y-1 font-mono text-[10px] text-muted-foreground">
                  <p className="truncate">hash: {b.hash}</p>
                  <p className="truncate">prev: {b.prevHash}</p>
                </div>
              </button>
            ))}
          </div>

          {openBlock !== null && chain[openBlock] && (
            <div className="mt-6 rounded-xl border border-border/70 bg-background/80 p-5 font-mono text-xs">
              <div className="flex items-center justify-between text-muted-foreground pb-2 border-b border-border/40">
                <span>Block #{chain[openBlock]!.index} Inspector</span>
                <span>{chain[openBlock]!.timestamp}</span>
              </div>
              <pre className="mt-3 overflow-x-auto text-[11px] text-foreground leading-relaxed">
{JSON.stringify(chain[openBlock], null, 2)}
              </pre>
            </div>
          )}
        </div>
      </Section>
    </>
  );
}
