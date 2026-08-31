import { cn } from "@/lib/utils";

/** Official Gemini sparkle (hosted by Google: gstatic.com/lamda). */
export function GeminiMark({ className = "size-4" }: { className?: string }) {
  return (
    <img
      src="/logos/gemini.svg"
      alt=""
      width={16}
      height={16}
      className={cn("inline-block object-contain", className)}
    />
  );
}

/** Official Google Cloud four-color hex mark. */
export function GoogleCloudMark({ className = "size-4" }: { className?: string }) {
  return (
    <img
      src="/logos/google-cloud.svg"
      alt=""
      width={16}
      height={16}
      className={cn("inline-block object-contain", className)}
    />
  );
}

/** Official Google G (fonts.gstatic.com product logo). */
export function GoogleGMark({ className = "size-4" }: { className?: string }) {
  return (
    <img
      src="/logos/google-g.svg"
      alt=""
      width={16}
      height={16}
      className={cn("inline-block object-contain", className)}
    />
  );
}

/** Official Agent Development Kit mark (google/adk-python assets). */
export function AdkMark({ className = "size-4" }: { className?: string }) {
  return (
    <img
      src="/logos/google-adk.png"
      alt=""
      width={16}
      height={16}
      className={cn("inline-block object-contain", className)}
    />
  );
}

export function BrandChip({
  mark,
  label,
}: {
  mark: "gemini" | "cloud" | "google" | "adk";
  label: string;
}) {
  const Icon =
    mark === "gemini" ? GeminiMark : mark === "cloud" ? GoogleCloudMark : mark === "adk" ? AdkMark : GoogleGMark;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-black/35 px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.12em] text-zinc-300">
      <Icon className="size-3.5 shrink-0" />
      {label}
    </span>
  );
}
