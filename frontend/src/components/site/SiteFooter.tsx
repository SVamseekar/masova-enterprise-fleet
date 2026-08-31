import { ShieldCheck } from "lucide-react";
import { CONSOLE_PATH } from "@/lib/console";
import { AdkMark, GeminiMark, GoogleCloudMark } from "@/components/site/GoogleMarks";

const COLUMNS = [
  {
    title: "Demo",
    links: [
      { href: CONSOLE_PATH, label: "Manager console" },
      { href: "#copilot", label: "Manager Copilot" },
      { href: "#agents", label: "The fleet" },
    ],
  },
  {
    title: "Governance",
    links: [
      { href: "#kya", label: "Know-Your-Agent matrix" },
      { href: "#audit", label: "SHA-256 audit ledger" },
      { href: "#architecture", label: "Architecture" },
    ],
  },
  {
    title: "Source",
    links: [
      { href: "#stack", label: "Architecture notes" },
      { href: "https://github.com/SVamseekar/masova-enterprise-fleet", label: "GitHub repository" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-border/60 bg-card/30">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-4 lg:px-8">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-lg bg-[image:var(--gradient-primary)] text-primary-foreground">
              <ShieldCheck className="size-4.5" strokeWidth={2.4} />
            </span>
            <span className="font-display text-lg font-semibold">
              Ma<span className="text-primary">So</span>Va Fleet
            </span>
          </div>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
            A governed multi-agent operations fleet for restaurant groups. Agents propose, managers
            decide, and every decision is hash-chained.
          </p>
          <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.14em] text-primary">
            Agents propose · managers decide
          </p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.title}>
            <h3 className="text-sm font-semibold">{col.title}</h3>
            <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
              {col.links.map((l) => (
                <li key={l.label}>
                  <a href={l.href} className="hover:text-foreground">
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-border/60 px-4 py-6 text-center font-mono text-[11px] text-muted-foreground">
        <span className="inline-flex flex-wrap items-center justify-center gap-3">
          <span className="inline-flex items-center gap-1.5">
            <AdkMark className="size-3.5" /> Google ADK
          </span>
          <span className="inline-flex items-center gap-1.5">
            <GeminiMark className="size-3.5" /> Gemini 3.7 Flash
          </span>
          <span className="inline-flex items-center gap-1.5">
            <GoogleCloudMark className="size-3.5" /> Google Cloud Run
          </span>
        </span>
      </div>
    </footer>
  );
}
