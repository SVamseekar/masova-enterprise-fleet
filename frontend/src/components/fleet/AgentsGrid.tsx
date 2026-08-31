import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AGENTS, type Agent } from "@/lib/masova-data";
import { Section } from "@/components/site/Section";
import { FleetBrigade, STATION } from "@/components/fleet/FleetBrigade";

const COPILOT = AGENTS.find((a) => a.id === "manager-copilot")!;
const SPECIALISTS = AGENTS.filter((a) => a.id !== "manager-copilot");

export function AgentsGrid() {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<Agent | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SPECIALISTS;
    return SPECIALISTS.filter((a) =>
      [a.name, a.role, a.summary, STATION[a.id], ...a.tools, ...a.capabilities]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [query]);

  return (
    <Section
      id="agents"
      eyebrow="The fleet"
      title="Seven specialists. One pass."
      description="The brigade around the expeditor. Specialists draft from their station; every ticket travels inward. Nothing leaves the pass without a manager."
      photo="ops"
    >
      <div className="mb-6 relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search stations, tools, capabilities…"
          className="w-full rounded-xl border border-border bg-card/80 px-3.5 py-2.5 pl-9 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">No stations match that search.</p>
      ) : (
        <FleetBrigade
          specialists={filtered}
          copilot={COPILOT}
          hovered={hovered}
          onHover={setHovered}
          onSelect={setActive}
        />
      )}

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="max-w-2xl">
          {active && (
            <>
              <DialogHeader>
                <div className="flex items-center gap-3">
                  <span className="grid size-11 place-items-center rounded-xl bg-[image:var(--gradient-primary)] text-primary-foreground">
                    <active.icon className="size-5" />
                  </span>
                  <div>
                    <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-primary">
                      {STATION[active.id]}
                    </p>
                    <DialogTitle className="text-xl">{active.name}</DialogTitle>
                    <DialogDescription>{active.role}</DialogDescription>
                  </div>
                </div>
              </DialogHeader>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{active.summary}</p>
              <div className="mt-4 space-y-3">
                <div>
                  <h4 className="font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Declared tools
                  </h4>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {active.tools.map((t) => (
                      <span key={t} className="rounded bg-secondary px-2 py-1 font-mono text-xs text-primary">
                        {t}()
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-primary/30 bg-primary/10 p-3 text-xs text-foreground">
                  <strong className="text-primary">Guardrails:</strong> {active.guardrails}
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Section>
  );
}
