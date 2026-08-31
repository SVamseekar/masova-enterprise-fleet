import { motion } from "framer-motion";
import type { ReactNode } from "react";

export function Section({
  id,
  eyebrow,
  title,
  description,
  children,
  className = "",
  photo,
}: {
  id?: string;
  eyebrow?: string;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  photo?: "kitchen" | "office" | "cellar" | "ops" | "command" | "supply";
}) {
  const photoClass =
    photo === "kitchen"
      ? "photo-kitchen"
      : photo === "office"
        ? "photo-office"
        : photo === "cellar"
          ? "photo-cellar"
          : photo === "ops"
            ? "photo-ops"
            : photo === "command"
              ? "photo-command"
              : photo === "supply"
                ? "photo-supply"
                : "";
  return (
    <section
      id={id}
      className={`relative scroll-mt-20 overflow-hidden py-16 sm:py-24 ${className}`}
    >
      {photo && (
        <div className="pointer-events-none absolute inset-0" aria-hidden>
          <div className={`photo-recess absolute inset-0 ${photoClass}`} />
          <div className="photo-veil absolute inset-0" />
          <div className="film-grain" />
        </div>
      )}
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {(eyebrow || title) && (
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
            className="mb-10 max-w-3xl"
          >
            {eyebrow && (
              <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-primary font-mono">
                {eyebrow}
              </p>
            )}
            {title && (
              <h2 className="text-3xl font-semibold leading-tight sm:text-4xl">{title}</h2>
            )}
            {description && (
              <p className="mt-4 text-base leading-relaxed text-muted-foreground">{description}</p>
            )}
          </motion.div>
        )}
        {children}
      </div>
    </section>
  );
}

export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.7, delay, ease: [0.16, 1, 0.3, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}
