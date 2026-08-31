import {
  Bot,
  TrendingUp,
  PackageSearch,
  HeartHandshake,
  MessageSquareQuote,
  CalendarClock,
  ChefHat,
  Tags,
  type LucideIcon,
} from "lucide-react";

export type Agent = {
  id: string;
  name: string;
  role: string;
  icon: LucideIcon;
  tier: "Read / Compute" | "Propose" | "Execute (blocked)";
  summary: string;
  capabilities: string[];
  tools: string[];
  guardrails: string;
};

export const AGENTS: Agent[] = [
  {
    id: "manager-copilot",
    name: "Manager Copilot",
    role: "Fleet Conductor & Voice RAG",
    icon: Bot,
    tier: "Read / Compute",
    summary:
      "The conversational conductor of the fleet. Grounds every answer in the store's ops manual and live telemetry, then narrates it back with voice synthesis.",
    capabilities: [
      "Retrieval-augmented answers over HACCP & ops manuals",
      "Cross-store performance comparison in natural language",
      "Delegates tasks to the seven specialist agents",
      "Voice narration for hands-free line management",
    ],
    tools: ["search_ops_manual", "compare_store_performance", "delegate_to_agent", "synthesize_voice"],
    guardrails: "Read-only access to fleet data. Cannot mutate menus, prices, or orders.",
  },
  {
    id: "demand-forecaster",
    name: "Demand Forecaster",
    role: "Weighted Moving Average + GenAI",
    icon: TrendingUp,
    tier: "Read / Compute",
    summary:
      "Blends a 28-day weighted moving average with Gemini reasoning over weather, local events, and holiday calendars to project covers per daypart.",
    capabilities: [
      "Per-daypart cover forecasts from sales history, weather, and local events",
      "Weather & event signal fusion",
      "Prep quantity recommendations per recipe",
      "Feeds Inventory Watcher and Shift Optimizer",
    ],
    tools: ["fetch_sales_history", "get_weather_signal", "compute_wma", "publish_forecast"],
    guardrails: "Compute-only tier. Emits forecasts, never purchase or staffing commitments.",
  },
  {
    id: "inventory-watcher",
    name: "Inventory Watcher",
    role: "Automated PO Drafting",
    icon: PackageSearch,
    tier: "Propose",
    summary:
      "Watches live stock depletion against par levels and drafts supplier purchase orders the moment a threshold breach is projected.",
    capabilities: [
      "Par-level breach detection per SKU",
      "Supplier lead-time aware PO drafting",
      "Waste & shrinkage anomaly flagging",
      "Recipe-linked cost impact preview",
    ],
    tools: ["read_stock_levels", "get_supplier_catalog", "draft_purchase_order"],
    guardrails: "Drafts only. A PO is never transmitted to a supplier without manager approval.",
  },
  {
    id: "churn-prevention",
    name: "Churn Prevention Specialist",
    role: "GDPR-safe segmentation",
    icon: HeartHandshake,
    tier: "Propose",
    summary:
      "Segments lapsing VIP regulars from loyalty telemetry and drafts re-engagement offers — with consent enforcement baked into the query itself.",
    capabilities: [
      "RFM-based lapse detection",
      "Consent-filtered audience building",
      "Offer value bounded by lifetime-margin",
      "Automatic exclusion audit trail",
    ],
    tools: ["segment_customers", "check_marketing_consent", "draft_campaign"],
    guardrails: "Customers without explicit marketing consent are removed before drafting.",
  },
  {
    id: "review-responder",
    name: "Review Responder",
    role: "Brand sentiment & multi-lingual replies",
    icon: MessageSquareQuote,
    tier: "Propose",
    summary:
      "Reads inbound reviews across platforms, classifies sentiment and theme, and drafts on-brand replies in the reviewer's own language.",
    capabilities: [
      "Sentiment & theme clustering by store",
      "Reply drafting in 14 languages",
      "Escalation routing for food-safety complaints",
      "Brand tone-of-voice enforcement",
    ],
    tools: ["fetch_reviews", "classify_sentiment", "draft_reply"],
    guardrails: "No reply is published autonomously; GM approval is required per response.",
  },
  {
    id: "shift-optimizer",
    name: "Shift Optimizer",
    role: "EU labor law compliance & skill matching",
    icon: CalendarClock,
    tier: "Propose",
    summary:
      "Builds schedules that satisfy forecast demand while respecting rest periods, weekly caps, and minor-employee rules across EU jurisdictions.",
    capabilities: [
      "Demand-matched shift construction",
      "11h rest & 48h weekly cap enforcement",
      "Skill/station coverage matching",
      "Labor-cost percentage targeting",
    ],
    tools: ["get_forecast", "read_staff_roster", "validate_labor_rules", "draft_schedule"],
    guardrails: "Schedules are proposals. Publishing requires manager sign-off.",
  },
  {
    id: "kitchen-coach",
    name: "Kitchen Coach",
    role: "Prep line bottleneck detection & HACCP alerts",
    icon: ChefHat,
    tier: "Read / Compute",
    summary:
      "Monitors KDS ticket timings station-by-station, surfaces the true bottleneck, and raises HACCP alerts before a temperature log goes stale.",
    capabilities: [
      "Station-level ticket time analysis",
      "Bottleneck root-cause narration",
      "HACCP log gap detection",
      "Rush-hour pacing coaching prompts",
    ],
    tools: ["read_kds_metrics", "check_haccp_logs", "emit_coaching_prompt"],
    guardrails: "Advisory only. Cannot re-route or void live tickets.",
  },
  {
    id: "dynamic-pricing",
    name: "Dynamic Pricing Strategist",
    role: "Bounded pricing guardrails",
    icon: Tags,
    tier: "Propose",
    summary:
      "Proposes off-peak promotional adjustments on slow-moving items, hard-capped at 10% and blocked from ever breaching the item margin floor.",
    capabilities: [
      "Off-peak elasticity modelling",
      "Slow-mover clearance proposals",
      "Margin-floor protection",
      "Competitive basket awareness",
    ],
    tools: ["read_item_velocity", "compute_elasticity", "draft_price_change"],
    guardrails: "Discounts capped at 10%. Menu prices are never written without approval.",
  },
];

export type ProposalSeed = {
  id: string;
  agent: string;
  agentId: string;
  title: string;
  store: string;
  rationale: string;
  impact: string;
  confidence: number;
  risk: "Low" | "Medium";
  badges: string[];
  detail: { label: string; value: string }[];
  note?: string;
};

export const PROPOSAL_SEEDS: ProposalSeed[] = [
  {
    id: "PRP-4471",
    agent: "Dynamic Pricing Strategist",
    agentId: "dynamic-pricing",
    title: "Off-peak -8% on slow-moving croissants",
    store: "Paris DOM011",
    rationale:
      "Rain forecast 14:00–17:00 with 31% below-baseline footfall. 42 viennoiseries at risk of end-of-day waste.",
    impact: "+€118 recovered revenue · −11kg projected waste",
    confidence: 0.87,
    risk: "Low",
    badges: ["Capped at 10%", "Margin protected"],
    detail: [
      { label: "Item", value: "Croissant au beurre · Pain au chocolat" },
      { label: "Window", value: "Today 14:00 – 17:00" },
      { label: "Adjustment", value: "−8% (cap −10%)" },
      { label: "Margin floor", value: "58% → 53% (floor 48%)" },
    ],
  },
  {
    id: "PRP-4472",
    agent: "Inventory Watcher",
    agentId: "inventory-watcher",
    title: "Draft PO €245 — Organic EVOO restock",
    store: "Paris DOM011",
    rationale:
      "3.2L remaining against a 15L par level. Supplier BioVrac lead time is 48h; breach projected in 19h.",
    impact: "Prevents 2 menu items going 86 across Friday service",
    confidence: 0.94,
    risk: "Low",
    badges: ["Supplier: BioVrac", "Lead time 48h"],
    detail: [
      { label: "SKU", value: "EVOO-ORG-5L · Organic extra virgin olive oil" },
      { label: "On hand", value: "3.2 L (par 15 L)" },
      { label: "Order qty", value: "4 × 5L cases" },
      { label: "PO value", value: "€245.00 excl. VAT" },
    ],
  },
  {
    id: "PRP-4473",
    agent: "Churn Prevention Specialist",
    agentId: "churn-prevention",
    title: "Re-engagement offer for 12 lapsed VIP regulars",
    store: "Paris DOM011",
    rationale:
      "15 VIP guests with 90+ days since last visit and lifetime spend above €480. Consent filter applied before drafting.",
    impact: "Projected 4 returning covers · +€310 expected revenue",
    confidence: 0.71,
    risk: "Medium",
    badges: ["GDPR consent enforced"],
    note: "3 customers excluded due to lack of marketing consent",
    detail: [
      { label: "Audience", value: "12 of 15 matched guests" },
      { label: "Offer", value: "Complimentary dessert on next visit" },
      { label: "Channel", value: "Email (opt-in only)" },
      { label: "Expiry", value: "21 days" },
    ],
  },
];

export type LedgerBlock = {
  index: number;
  timestamp: string;
  agent: string;
  action: string;
  store: string;
  outcome: "APPROVED" | "DECLINED";
  prevHash: string;
  hash: string;
};

export const INITIAL_LEDGER: LedgerBlock[] = [
  {
    index: 812,
    timestamp: "11:42:04 UTC",
    agent: "Demand Forecaster",
    action: "PUBLISH_FORECAST · covers=142 window=lunch",
    store: "Paris DOM011",
    outcome: "APPROVED",
    prevHash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    hash: "a4f81c9b2e7d0f3a6b5c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a",
  },
  {
    index: 813,
    timestamp: "12:05:19 UTC",
    agent: "Inventory Watcher",
    action: "PO_DRAFT · supplier=BioVrac sku=EVOO-5L amount=€245",
    store: "Paris DOM011",
    outcome: "APPROVED",
    prevHash: "a4f81c9b2e7d0f3a6b5c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a",
    hash: "7f2e1a9c8b0d4f3a5e6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f",
  },
];
