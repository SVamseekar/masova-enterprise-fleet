import { motion } from "framer-motion";
import { Github, Menu, ShieldCheck, Terminal, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { CONSOLE_PATH } from "@/lib/console";

const LINKS = [
  { hash: "overview", label: "Governance" },
  { hash: "agents", label: "The fleet" },
  { hash: "audit", label: "Audit ledger" },
  { hash: "architecture", label: "Architecture" },
];

export function SiteNav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <a href="#" className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-[image:var(--gradient-primary)] text-primary-foreground">
            <ShieldCheck className="size-4.5" strokeWidth={2.4} />
          </span>
          <span className="leading-tight">
            <span className="block font-display text-base font-semibold tracking-tight">
              Ma<span className="text-primary">So</span>Va Fleet
            </span>
            <span className="block font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              Manager Copilot
            </span>
          </span>
        </a>

        <div className="hidden items-center gap-0.5 xl:flex">
          {LINKS.map((l) => (
            <motion.a
              key={l.hash}
              href={`#${l.hash}`}
              whileHover={{ y: -1 }}
              className="rounded-full px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              {l.label}
            </motion.a>
          ))}
        </div>

        <div className="hidden items-center gap-2 xl:flex">
          <Button asChild variant="ghost" size="sm">
            <a href="https://github.com/SVamseekar/masova-enterprise-fleet" target="_blank" rel="noreferrer">
              <Github className="size-4" /> Source
            </a>
          </Button>
          <Button asChild variant="hero" size="sm">
            <a href={CONSOLE_PATH}>
              <Terminal className="size-4" /> Open the console
            </a>
          </Button>
        </div>

        <button
          className="grid size-9 place-items-center rounded-md border border-border text-foreground xl:hidden"
          aria-label="Toggle navigation"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? <X className="size-4" /> : <Menu className="size-4" />}
        </button>
      </nav>

      {open && (
        <div className="border-t border-border/60 px-4 py-3 xl:hidden">
          {LINKS.map((l) => (
            <a
              key={l.hash}
              href={`#${l.hash}`}
              onClick={() => setOpen(false)}
              className="block rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              {l.label}
            </a>
          ))}
          <div className="mt-2 grid gap-2">
            <Button asChild variant="subtle" size="sm">
              <a href="https://github.com/SVamseekar/masova-enterprise-fleet" target="_blank" rel="noreferrer">
                <Github className="size-4" /> Source
              </a>
            </Button>
            <Button asChild variant="hero" size="sm">
              <a href={CONSOLE_PATH} onClick={() => setOpen(false)}>
                <Terminal className="size-4" /> Open the console
              </a>
            </Button>
          </div>
        </div>
      )}
    </header>
  );
}
