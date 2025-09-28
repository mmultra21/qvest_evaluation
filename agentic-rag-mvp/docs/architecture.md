# Architecture — agentic-rag-mvp

This document describes the high-level architecture of the Student → Judge → Admin approval flow and where `hermes3` fits into the design.

```mermaid
flowchart LR
  Student[Student client] -->|logs finished book| Planner[Planner / Agent Job]
  Planner -->|writes per-book audit_logs| DB[(SQLite agent.db)]
  DB --> Judge[LLM Judge]
  Judge -- model: hermes3 --> ModelHermes[hermes3 LLM provider]
  Judge -- fallback --> Fallback[HTTP client / heuristic fallback]
  Judge -->|writes judge_logs (score, label, reason)| DB
  AdminUI[Admin UI (Gradio)] -->|views pending audit_logs| DB
  AdminUI -->|approve/reject| DB
  style ModelHermes fill:#f9f,stroke:#333,stroke-width:1px
  style Fallback fill:#fee,stroke:#333,stroke-width:1px
```

Notes

- hermes3 is the primary LLM used by the judge component. When `hermes3` responds, its structured output (score/label/reason) is stored in `judge_logs.reason`. In some historical records the raw model JSON is stored as a string; consider migrating or adding a dedicated `raw_response` column for clarity.
- The judge scaffold includes an HTTP fallback and a deterministic heuristic fallback; if `hermes3` fails or returns an empty output, the fallback paths are used before giving up. These fallbacks are shown in the diagram.
- The Admin UI displays the latest judge metadata (id, score, label, snippet of reason) and includes a "View full judge JSON" control to inspect raw responses from `hermes3` or fallbacks.
- The auto-approve flow uses a configured threshold (AUTO_APPROVE_THRESHOLD) to mark rows as `approved` automatically when the latest judge score >= threshold.

Recommended follow-ups

- Add a short migration that copies/normalizes the raw JSON model output into a new `judge_logs.raw_response` TEXT column so the UI and analytics can parse it reliably.
- Add an architecture diagram image to `docs/` for human-friendly rendering in places that don't render Mermaid.

