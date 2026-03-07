# LeadWise Sales Agent — Product Requirements Document

**Version:** 1.0
**Date:** 2026-03-07
**Status:** Draft

---

## 1. Executive Summary

LeadWise is a multi-tenant AI sales agent SaaS platform that operates over WhatsApp. It automates lead qualification, sales conversations, and appointment booking for businesses. Each business (tenant) runs on shared infrastructure but with fully isolated data, configuration, and conversation logic.

The platform is designed to be generic at the infrastructure level and flexible at the business logic level — each tenant can have a different conversation graph, CRM integration, LLM provider, and persona.

---

## 2. Problem Statement

Sales and service teams spend significant time on repetitive WhatsApp conversations: qualifying leads, answering FAQs, collecting basic info, and booking appointments. This work is:

- **Slow** — human response times are inconsistent, especially outside business hours
- **Expensive** — human agents cost money at scale
- **Inconsistent** — quality varies per agent
- **Hard to scale** — adding clients means adding headcount

LeadWise solves this by deploying an AI agent per tenant that handles the full conversation automatically, 24/7, only escalating to a human when necessary.

---

## 3. Platform Vision

### Core Principle
> Generic infrastructure. Per-client logic.

The platform provides shared, production-grade infrastructure (message ingress, tenant routing, memory, observability, rate limiting, DLQ). Each client gets their own conversation graph (LangGraph) and configuration.

### Multi-Tenancy Model
- Each tenant is identified by their Green API `instanceId`
- Full data isolation at the database layer (app-level filtering in MVP, Postgres RLS in production)
- Per-tenant: system prompt, LLM provider/key, Green API credentials, CRM integration, enabled tools, persona
- Multiple phone numbers per tenant supported (e.g. sales line + support line)
- Fallback Green API instance per tenant (if primary is blocked or disconnected)

### Channel Strategy
- **Phase 0–6:** WhatsApp via Green API only
- **Future:** WhatsApp Business API, Telegram (architecture supports it via channel abstraction layer)

---

## 4. Clients

### 4.1 Client: Iroko

**Type:** Simple conversational sales agent
**Industry:** Hair clinic (hair transplants)
**CRM:** Internal Postgres
**Existing reference:** `Iroko-chatbot-green-API.json` (n8n workflow — for reference only, not production code)

**Conversation Flow:**
```
Inbound message
  → RAG search (FAQ / product knowledge)
  → Lead qualification (is this a real lead?)
  → Book appointment
  → Confirmation
```

**Key characteristics:**
- Open-ended conversational LLM agent
- Knowledge base in Qdrant (FAQ, treatments, pricing)
- Qualify lead before offering booking
- Escalate to human on request or after 2 failed interactions

---

### 4.2 Client: DNG Medical

**Type:** Complex deterministic state machine
**Industry:** Hair transplant clinic
**Bot Persona:** מאיה — Hebrew only, natural tone, concise, no "bot-speak", no excessive emojis
**CRM:** Biznness (bizsense.co.il) — external API *(docs + sandbox required before Phase 6)*
**Payment:** Hype (הייפ) — 180 NIS consultation fee, webhook-triggered
**Calendar:** Biznness API
**Invoice:** Auto PDF sent via WhatsApp post-payment

**Conversation Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| FLOW 0: Identify | First inbound message | CRM lookup → route to returning or new |
| FLOW 2: Returning | Returning customer | Collect treatment type (Mesotherapy/IPRF) + branch (PT/KS) + time preference → send calendar link |
| FLOW 3: Screening | New lead | 3 screening questions → hard disqualification check |
| FLOW 4: Sales | Passed screening | Sales pitch → payment link (180 NIS) → post-payment: calendar + Waze + PDF invoice |

**Medical Disqualification Rules (FLOW 3 — hard rules):**
- Must be 22+
- No full baldness
- No oncological disease
- No neurological disease
- No psoriasis in hair
- No blood thinners / serious chronic conditions

If disqualified → update CRM status to "אי התאמה" → escalate to human agent.

**Edge Cases:**

| Case | Behavior |
|------|---------|
| Human Handoff | Triggered on 2nd explicit request OR 2nd gibberish input. Stop bot, update CRM to "מעבר לנציג", message: "הבקשה הועברה, נחזור אליך תוך 24 שעות בימי עסקים" |
| Abandonment / Timeout | PING 1 after 1hr, PING 2 after 3 days. Update CRM accordingly ("נטש בסליקה" / "לא מעוניין") |
| Appointment Reminders | 7 days before (confirmation request), 1 business day before at 14:00, morning of at 07:00 |
| Cancellation | >48h: full refund + reschedule. 24–48h: reschedule only. <24h: no refund, no change |
| Photos | Optional, stored to Biznness CRM. No bot analysis. |
| Invalid input (gibberish/image) | First time: clarify. Second time: human handoff |

**CRM Status Values (to be created in Biznness):**
- אי התאמה
- שילם דמי רצינות
- מעבר לנציג
- נטש בסליקה
- נקבעה פגישת ייעוץ

---

## 5. Generic Platform Capabilities

These are provided by the shared infrastructure for all tenants:

| Capability | Description |
|-----------|-------------|
| Message ingress | Webhook from Green API, parsed + deduplicated |
| Tenant routing | Map instanceId → tenant config |
| Async processing | ARQ job queue (Redis-backed) |
| Conversation memory | Postgres-backed chat history + summarizer |
| RAG / knowledge base | Qdrant vector search, per-tenant collection |
| LLM invocation | LiteLLM (any provider, per-tenant key) |
| Outbound messaging | Green API client with typing simulation |
| Message formatting | Markdown → WhatsApp plain text converter |
| Human handoff | Escalation signal → CRM status update |
| Rate limiting | Per-tenant sliding window (Redis) |
| DLQ | Failed messages stored + replayable |
| Observability | OTel traces + metrics + logs → SigNoz |
| Audit trail | Every agent run + tool call logged |

---

## 6. Per-Client Customization Surface

Each tenant can configure:

| Config | Type | Example |
|--------|------|---------|
| `graph_type` | Enum | `iroko` / `dng` / future types |
| `system_prompt` | Text | Bot persona, instructions |
| `llm_provider` | String | `anthropic/claude-sonnet-4-6` (default) |
| `llm_api_key` | Secret | Stored in secrets store |
| `green_api_instance_id` | String | Green API instance |
| `green_api_token` | Secret | Green API auth |
| `green_api_fallback_instance_id` | String | Optional fallback number |
| `crm_integration` | Object | Type + credentials per CRM |
| `tools_enabled` | List | e.g. `[vector_search, book_meeting, escalate]` |
| `qdrant_collection` | String | Per-tenant vector collection name |
| `rate_limit_rpm` | Int | Max messages per minute |
| `llm_monthly_token_cap` | Int | Cost control |

---

## 7. Technical Decisions (Locked)

| Decision | Choice | Reason |
|---------|--------|--------|
| Language | Python | Team preference, AI ecosystem |
| API Framework | FastAPI 0.115+ | Async, OpenAPI, DI |
| ORM | SQLAlchemy 2.0 async + Alembic | Mature, RLS-ready |
| Agent Orchestration | LangGraph + Factory Pattern | Scalable, per-client graphs, industry standard |
| LLM Abstraction | LiteLLM | Swap providers without code changes |
| Background Jobs | ARQ | Lightweight, Redis-native, async |
| Cache / Queue / Rate Limit | Redis 7 | Single dependency for 3 concerns |
| Vector DB | Qdrant | Already in use, per-tenant collections |
| WhatsApp | Green API | Already in use |
| Observability | OpenTelemetry → SigNoz | Full stack: traces + metrics + logs |
| Secrets (MVP) | Environment variables | Simple, secure enough for MVP |
| Secrets (Prod) | HashiCorp Vault | Production-grade |
| Deploy (MVP) | Docker Compose | Fast to ship |
| Deploy (Prod) | Kubernetes | Scale safely |

---

## 8. Out of Scope (MVP)

- Admin UI / web dashboard (CLI only for now)
- Telegram / WhatsApp Business API (future channels)
- Per-tenant billing / metering UI
- Outbound campaign initiation (bot only responds, does not initiate)
- Voice messages (text only in MVP; media transcription is Phase 4+)
- DNG graph (Phase 6 — blocked on Biznness API access)

---

## 9. Success Metrics

| Metric | Target |
|--------|--------|
| Lead response time | < 30 seconds |
| Human handoff rate | < 20% of conversations |
| Appointment booking rate | > 30% of qualified leads |
| No-show rate reduction | > 25% vs baseline (via reminders) |
| Onboarding a new tenant | < 30 minutes |
| System uptime | > 99.5% |
| Message delivery success | > 99% |

---

## 10. Open Blockers

| Blocker | Required For | Owner |
|---------|-------------|-------|
| Biznness API docs + sandbox credentials | Phase 6 (DNG graph) | DNG / Moshe |
| Hype payment webhook format | Phase 6 (DNG payment flow) | DNG / Moshe |
| Iroko system prompt (final version) | Phase 3 (Iroko graph) | Moshe |
| Green API sandbox instance for testing | Phase 2 (webhook ingress tests) | Moshe |

---

## 11. Build Phases

| Phase | Description |
|-------|-------------|
| **0** | PRD (this document) ✓ |
| **1** | Repo scaffold: pyproject.toml, Docker Compose, Postgres, Redis, Qdrant ✓ |
| **2** | FastAPI skeleton, Green API webhook ingress, tenant routing, dedup ✓ |
| **3** | LangGraph factory + Iroko graph + core tools (RAG, CRM, escalate, book) ← IN PROGRESS |
| **4** | Conversation memory, RAG pipeline, Qdrant seeding scripts |
| **5** | Observability (OTel → SigNoz), rate limiting, DLQ + replay |
| **6** | DNG graph — medical screening state machine *(blocked: needs Biznness API)* |
| **7** | Admin CLI, onboarding playbook, `.env.example` |
| **8** | Production hardening: Postgres RLS, Vault, K8s manifests |
