# Reasoning-Chain Observability — Design Spec

Status: draft (auto-authored per user instruction to proceed through all 7 phases without per-decision confirmation)
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 3 — "Is it behaving right now?"
Depends on: Phase 1's persisted run store (`data/runs/runs.jsonl`, `runtime/audit.py` extension)

## Problem

`AuditLogger.log_run()` (`runtime/audit.py`) records a run's *outcome* —
`tools_used` as a flat list of names, proposal summaries, `used_fallback`,
latency — but not the *sequence*: which tool was called with what
arguments, in what order, with what result, and how long each step took.
There's also no tamper-evidence: a JSONL file (Phase 1's `data/runs/`) can
be edited after the fact with nothing to detect it.

## Constraint carried forward

The trace must be built from real tool-call events as they happen — not
reconstructed or faked after the fact from the flat `tools_used` list.

## Design

### Structured step capture

New dataclass in `runtime/models.py`:

```python
@dataclass
class ToolCallStep:
    index: int
    tool_name: str
    args: dict[str, Any]        # redacted via AuditLogger.SENSITIVE_KEYS before persist
    result_status: str          # "ok" | "error"
    result_summary: str         # truncated (500 char), redacted repr of the tool's actual return value
    duration_ms: float
    at: str                     # utc iso timestamp
```

`AgentRunResult` gains `reasoning_trace: list[ToolCallStep] = field(default_factory=list)`.

`result_summary` exists specifically so the trace answers "what data did
this tool actually see," not just "did it succeed" — this is the field
that lets a demo show an agent's decision traced back to a real row (e.g.
`list_low_stock` → `[{"item": "Mozzarella (kg)", "quantity": 3, ...}]`),
which a bare `result_status: "ok"` cannot. Truncated and redacted the same
way `AuditLogger.log_run`'s existing `summary`/`rationale` fields already
are (`[:500]`, `SENSITIVE_KEYS` scrub) — never the full untruncated,
unredacted payload.

### Ops tool loop (`runtime/ops_llm.py`)

The multi-step function-calling loop (~L127 and ~L251, where `tools_used.append(name)`
already fires per call) is the exact point to also append a `ToolCallStep` —
same loop, same iteration, no restructuring. `duration_ms` is measured
around the actual tool invocation already happening there; `args` come from
the real function-call arguments the model produced, not reconstructed.

### Chat (ADK `Runner`) path (`agent.py`)

`send_message_async`'s `_adk_path()` iterates `runner.run(...)` events
looking for `is_final_response()`. Extend that same loop to also inspect
each event's `content.parts` for `function_call` / `function_response`
parts (the same shape `ops_llm.py` already reads at `fc = getattr(part,
"function_call", None)`), appending one `ToolCallStep` per pair. This reuses
existing event data ADK already emits — no new instrumentation of the LLM
call itself.

### Persistence + hash chain (extends Phase 1's run store)

`runtime/run_store.py` (introduced in Phase 1) gains tamper-evidence:
each appended JSONL line includes `record_hash = sha256(prev_hash +
canonical_json(record))`, `prev_hash` being the previous line's hash (or a
fixed genesis value for the first record). `canonical_json` = `json.dumps(...,
sort_keys=True, separators=(",", ":"))` so hashing is deterministic.

```python
def verify_chain(agent_name: str | None = None) -> bool:
    """Recomputes hashes over the persisted records; False on any break."""
```

This is the same tamper-evident-ledger shape the readiness plan cites from
`eu-ai-assurance-os`'s `AuditChainHasher`, reimplemented directly against
this service's own run-record shape (that repo isn't a dependency here).

### New endpoint

```
GET /agent/runs?agent=&limit=       require_scope("read:registry")  # Phase 2
GET /agent/runs/{run_id}
```

Returns the persisted `AgentRunResult` including `reasoning_trace`, plus
`chain_verified: bool` from `verify_chain()`.

## Error handling

- A tool-loop step that raises is still recorded (`result_status: "error"`),
  never dropped — an error mid-chain is itself part of the reasoning trace,
  not something to hide
- Hash chain verification failure never blocks reads — `GET /agent/runs`
  still returns data with `chain_verified: false` so the gap itself is
  visible rather than the endpoint failing closed

## Testing

New `tests/test_reasoning_trace.py`:

1. Scripted ops tool-loop test plan (already used in
   `tests/test_ops_llm_tools.py`) produces a `reasoning_trace` with one step
   per scripted tool call, in call order
2. Chat path: a mocked ADK event stream with two function calls produces a
   two-step trace
3. `verify_chain()` returns `True` on an untouched run store
4. Mutating one persisted line's content (without recomputing its hash)
   makes `verify_chain()` return `False`
5. A tool call that raises still appears in the trace with `result_status: "error"`
6. A tool call returning real data (e.g. `list_low_stock` against seeded
   demo rows) produces a `result_summary` containing that data, truncated
   and redacted the same way `AuditLogger`'s existing fields are — this is
   the field the demo cites to show a decision traced back to a real row

## Out of scope

- A UI for browsing traces → lives in the separate manager frontend repo,
  not this one (see Phase 6)
- Cross-run correlation / distributed tracing (OpenTelemetry spans) → real
  future work, no rubric line requires it for this submission
