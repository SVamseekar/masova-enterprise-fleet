import { Ban, Eye, FileSignature, Lock, ShieldCheck } from "lucide-react";
import { Reveal, Section } from "@/components/site/Section";

const TIERS = [
  {
    tier: "Read / Compute",
    icon: Eye,
    mode: "Auto-executed",
    tone: "emerald",
    description:
      "Querying telemetry, running forecasts, reading the ops manual and computing analytics. No state changes, so the fleet runs these continuously.",
    examples: ["fetch_sales_history", "compute_wma", "search_ops_manual", "read_kds_metrics"],
  },
  {
    tier: "Propose",
    icon: FileSignature,
    mode: "Drafted + manager notification · requires approval",
    tone: "primary",
    description:
      "Anything with a business consequence is drafted, signed and routed to the approval queue with full rationale and confidence.",
    examples: ["draft_purchase_order", "draft_price_change", "draft_campaign", "draft_schedule"],
  },
  {
    tier: "Execute",
    icon: Ban,
    mode: "Hard-blocked from executing on their own",
    tone: "destructive",
    description:
      "Write paths are revoked at the token layer. No silent POs, refunds, menu changes or guest messaging is technically possible without a human decision.",
    examples: ["transmit_po", "issue_refund", "publish_menu", "send_campaign"],
  },
];

export function GovernanceMatrix() {
  return (
    <Section
      id="kya"
      eyebrow="Know-Your-Agent"
      title="Governance is a permission tier, not a promise"
      description="Every tool in the registry is bound to a KYA tier at deploy time. The boundary is enforced by scoped tokens in the MaSoVa Core API — not by prompt instructions the model could ignore."
      photo="supply"
    >
      <div className="grid gap-4 lg:grid-cols-3">
        {TIERS.map((t, i) => (
          <Reveal key={t.tier} delay={i * 0.08}>
            <div className="surface h-full rounded-2xl border border-border/70 p-6">
              <div className="flex items-center justify-between">
                <span className="grid size-10 place-items-center rounded-xl bg-primary/15 text-primary">
                  <t.icon className="size-5" />
                </span>
                <span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-mono text-primary">
                  Tier {i + 1}
                </span>
              </div>
              <h3 className="mt-4 text-lg font-semibold">{t.tier}</h3>
              <p className="mt-1 text-xs font-medium text-primary">{t.mode}</p>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{t.description}</p>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {t.examples.map((e) => (
                  <span
                    key={e}
                    className="rounded-md border border-border bg-background/60 px-2 py-1 font-mono text-[10px] text-muted-foreground"
                  >
                    {e}()
                  </span>
                ))}
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </Section>
  );
}
