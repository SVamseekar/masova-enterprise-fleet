import { motion } from "framer-motion";
import { AudioLines, Bot, Loader2, Terminal, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/site/Section";
import { GeminiMark } from "@/components/site/GoogleMarks";

type Preset = {
  prompt: string;
  steps: string[];
  tools: string[];
  answer: string;
};

const PRESETS: Preset[] = [
  {
    prompt: "What is our HACCP protocol for raw seafood defrosting?",
    steps: [
      "Classify intent → ops_knowledge / food_safety",
      "Retrieve grounded chunks from Ops Manual v7 (Paris DOM011)",
      "Cross-check against EU Regulation 852/2004 annex II",
      "Compose answer with citation anchors",
    ],
    tools: ["search_ops_manual", "check_haccp_logs"],
    answer:
      "Defrost raw seafood in the dedicated ≤4 °C reach-in on the bottom shelf, in a perforated GN pan over a drip tray — never at ambient temperature and never under standing water. Log the start time on the blue HACCP sheet; maximum defrost window is 24 h. Product must reach the pass within 12 h of full defrost. Source: Ops Manual v7 §4.3 «Décongélation produits de la mer», aligned with EU 852/2004 Annex II Ch. IX.",
  },
  {
    prompt: "Compare Q3 labor efficiency between Paris DOM011 and Lyon DOM012",
    steps: [
      "Resolve store IDs and Q3 fiscal window",
      "Pull labor hours, covers and net sales per store",
      "Normalize by covers and daypart mix",
      "Rank drivers of variance",
    ],
    tools: ["compare_store_performance", "fetch_sales_history"],
    answer:
      "Paris DOM011 ran 27.9% labor cost vs Lyon DOM012 at 31.4%. Sales per labor hour: €62.10 (Paris) vs €53.80 (Lyon). The gap is concentrated in Lyon's Tue–Thu lunch block, which is over-staffed by roughly 1.4 FTE against forecast covers. Shift Optimizer estimates €2,180/month recoverable in Lyon without touching weekend coverage.",
  },
  {
    prompt: "Draft shift schedule for Sunday evening rush",
    steps: [
      "Load Demand Forecaster covers for Sunday 18:00–23:00",
      "Read staff roster, skills and remaining weekly hours",
      "Validate 11h rest and 48h weekly caps",
      "Draft schedule → route to approval queue",
    ],
    tools: ["get_forecast", "read_staff_roster", "validate_labor_rules", "draft_schedule"],
    answer:
      "Forecast is 214 covers (+18% vs last Sunday, clear weather + Fête de la Musique overlap). Draft: 3 line cooks (Camille, Yassine, Nora), 1 expediter (Marc), 4 FOH (Julie, Théo, Léa, Sami), 1 bar. Two 11 h-rest conflicts avoided by shifting Sami to a 19:00 start. Schedule is queued as a proposal — it will not publish until you approve it.",
  },
];

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex h-8 items-end gap-[3px]">
      {Array.from({ length: 32 }).map((_, i) => (
        <motion.span
          key={i}
          className="w-[3px] rounded-full bg-primary/80"
          animate={
            active
              ? { height: [4, 6 + ((i * 7) % 22), 4] }
              : { height: 4 + ((i * 3) % 5) }
          }
          transition={
            active
              ? { duration: 0.8 + (i % 5) * 0.12, repeat: Infinity, ease: "easeInOut" }
              : { duration: 0.3 }
          }
        />
      ))}
    </div>
  );
}

export function CopilotPlayground() {
  const [messages, setMessages] = useState<
    { role: "user" | "agent"; text: string; steps?: string[]; tools?: string[] }[]
  >([
    {
      role: "agent",
      text: "Manager Copilot online for Paris DOM011. I'm grounded on your ops manual, live POS telemetry and the fleet's agent registry. Ask me anything, or pick a preset.",
    },
  ]);
  const [thinking, setThinking] = useState<Preset | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  const run = (preset: Preset) => {
    if (thinking) return;
    setMessages((m) => [...m, { role: "user", text: preset.prompt }]);
    setThinking(preset);
    setSpeaking(true);
    setTimeout(() => {
      setMessages((m) => [
        ...m,
        {
          role: "agent",
          text: preset.answer,
          steps: preset.steps,
          tools: preset.tools,
        },
      ]);
      setThinking(null);
      setTimeout(() => setSpeaking(false), 2000);
    }, 1400);
  };

  return (
    <Section
      id="copilot"
      eyebrow="Manager Copilot"
      title={
        <>
          RAG over your ops manual · Gemini voice
        </>
      }
      description="The fleet's conversational front door. Answers store SOP questions with exact section citations, compares cross-store metrics, and simulates spoken audio playback for hands-free kitchen managers."
      photo="office"
    >
      <div className="surface grid overflow-hidden rounded-3xl border border-border/70 lg:grid-cols-[1.5fr_1fr]">
        <div className="flex flex-col border-b border-border/70 lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between border-b border-border/60 px-6 py-4">
            <div className="flex items-center gap-2.5">
              <span className="grid size-8 place-items-center rounded-lg bg-[image:var(--gradient-primary)] text-primary-foreground">
                <Bot className="size-4.5" />
              </span>
              <div>
                <p className="text-sm font-semibold">Manager Copilot</p>
                <p className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  <GeminiMark className="size-3" /> Gemini 3.7 Flash · Gemini voice · RAG
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Waveform active={speaking} />
              <AudioLines className={`size-4 ${speaking ? "text-primary animate-pulse" : "text-muted-foreground"}`} />
            </div>
          </div>

          <div ref={scroller} className="h-96 space-y-4 overflow-y-auto p-6">
            {messages.map((m, i) => (
              <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                {m.role === "agent" && (
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/15 text-primary text-xs">
                    AI
                  </span>
                )}
                <div
                  className={`max-w-md rounded-2xl p-4 text-xs leading-relaxed ${
                    m.role === "user"
                      ? "bg-primary text-primary-foreground font-medium"
                      : "surface border border-border/70 text-foreground"
                  }`}
                >
                  <p>{m.text}</p>
                  {m.tools && (
                    <div className="mt-3 flex flex-wrap gap-1 border-t border-border/40 pt-2 font-mono text-[10px] text-primary">
                      {m.tools.map((t) => (
                        <span key={t} className="rounded bg-background/60 px-1.5 py-0.5">
                          {t}()
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                {m.role === "user" && (
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-secondary text-xs">
                    <User className="size-3.5" />
                  </span>
                )}
              </div>
            ))}

            {thinking && (
              <div className="flex gap-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/15 text-primary text-xs">
                  <Loader2 className="size-3.5 animate-spin" />
                </span>
                <div className="surface max-w-md rounded-2xl border border-primary/40 p-4 text-xs space-y-2">
                  <p className="font-mono text-[10px] uppercase tracking-wider text-primary">Agent reasoning loop</p>
                  {thinking.steps.map((s, idx) => (
                    <div key={idx} className="flex items-center gap-2 text-muted-foreground">
                      <span className="font-mono text-[9px] text-primary">0{idx + 1}</span>
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="p-6 bg-card/30 flex flex-col justify-between">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground font-mono">
              Interactive Presets
            </h4>
            <div className="mt-4 space-y-2.5">
              {PRESETS.map((p, i) => (
                <button
                  key={i}
                  onClick={() => run(p)}
                  disabled={!!thinking}
                  aria-label={`Ask: ${p.prompt}`}
                  className="surface w-full rounded-xl border border-border/70 p-3.5 text-left text-xs font-medium transition-colors hover:border-primary/60 disabled:opacity-50"
                >
                  <p className="text-foreground">{p.prompt}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="mt-6 rounded-xl border border-border/70 bg-background/50 p-3.5 font-mono text-[11px] text-muted-foreground">
            <p className="text-primary font-bold">RAG Corpus Index:</p>
            <p className="mt-1">food_safety_haccp.md · labor_compliance_eu.md · supplier_slas.md</p>
          </div>
        </div>
      </div>
    </Section>
  );
}
