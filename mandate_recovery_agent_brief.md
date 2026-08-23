# Project brief: mandate step-up recovery agent
### For Razorpay AI Buildathon — Track 3 (AI Revenue Recovery)

## 1. One-liner
Build an agent that detects failed recurring payments caused by the RBI's ₹15,000 additional-authentication (AFA) threshold, classifies the exact failure type, executes the *compliant* recovery flow instead of the *broken* one, and reports measured money recovered on a synthetic batch — with a full audit trail.

## 2. Why this problem (context for the agent)
Under RBI e-mandate rules, recurring card/UPI payments above ₹15,000 require a per-transaction step-up approval (OTP) on the *existing* mandate — not a new mandate registration. Multiple independent merchants have publicly reported that this step-up breaks in practice: instead of a lightweight re-approval, the system spawns a full new mandate registration, which fails before the actual charge goes through. Separately, RuPay cards have a confirmed hard limit: recurring debits above ₹15,000 aren't supported on that rail at all yet. Every one of these failures is a subscription that lapses or an invoice that goes unpaid — that's the revenue this agent recovers.

## 3. Scope — read this before writing any code
This is the most important section. Get this wrong and the whole build is misdirected.

- Razorpay's **test-mode APIs** process transactions cleanly by design — they will NOT reproduce the real bank-side AFA rejection or the broken-mandate bug. Do not expect test-mode calls to fail the way the real bug fails.
- Therefore: **the failure events themselves must come from a synthetic dataset we generate**, designed to mirror the real documented failure patterns (see schema in section 5). Real Razorpay test-mode APIs are used only for the plumbing that *is* realistic to demo — e.g. generating a payment link for a step-up approval, creating a subscription, checking payment status.
- We are not patching Razorpay's actual production system. We are building the decision-and-recovery layer that should sit in front of this class of failure. Be explicit about this boundary in the README and the pitch — don't imply the system fixes Razorpay's real bug.

## 4. Core components to build
1. **Synthetic failed-payment generator** — produces a labeled batch of failed recurring transactions across several root causes (see section 5).
2. **Root-cause classifier** — deterministic, rule-based, explainable. Given a transaction's metadata, decides which failure category it belongs to and *why* (log the rule that fired — no black-box scoring here, the underlying regulation is deterministic, not fuzzy).
3. **Recovery orchestrator (the agent)** — this is the actually-agentic part of the system. An LLM reasons over the classified failure + attempt history + promise-to-pay state and decides its next move by calling one of a fixed set of tools. It does not free-write actions — it can only call pre-approved tools, which is what keeps it bounded. Full spec in section 8.
4. **Two simulated paths for comparison** — a "compliant flow" (step-up on the same mandate) and a "naive/broken flow" (spawns a new mandate). Running both against the same batch is what produces your headline recovery-rate delta.
5. **Retry scheduler with stopping rules** — bounded attempts, defined backoff, explicit give-up condition.
6. **Notification generator** — LLM-drafted, Hinglish, explains what approval is needed and why. Log every prompt/response pair.
7. **Promise-to-pay tracker** — records customer commitments, follows up once if missed, then respects the stopping rule.
8. **Audit trail** — every decision (classification, action, retry, notification, stop) logged with a machine-readable reason and timestamp.
9. **Metrics dashboard** — computes and displays the numbers in section 10 live from the batch run, not hardcoded.

## 5. Synthetic dataset schema
Generate 100–300 labeled synthetic failed-recurring-payment records. Suggested fields:

```
transaction_id, customer_id, merchant_id, mandate_id (UMRN),
amount, currency, mandate_ceiling, card_network (visa/mastercard/rupay/upi),
decline_code, failure_category, attempt_number, previous_attempts[],
timestamp, ground_truth_recoverable (bool), correct_action (label for eval)
```

`failure_category` values to include: `afa_stepup_required`, `rupay_hard_block`, `insufficient_funds`, `expired_card`, `other`. Weight the batch so `afa_stepup_required` is the dominant category — that's the one your agent is actually solving.

## 6. Classification rules (keep explainable)
- amount > mandate_ceiling AND card_network != rupay → `afa_stepup_required`
- amount > 15,000 AND card_network == rupay → `rupay_hard_block`
- decline_code indicates funds/card issue → `insufficient_funds` / `expired_card`
- Log which rule fired for every classification — this is your "honest metrics" evidence for judges.

## 7. Recovery workflow rules
- `afa_stepup_required` → generate a step-up approval request (payment link + OTP) tied to the *same* mandate_id. Never spawn a new mandate. This is the compliant path.
- `rupay_hard_block` → do not retry on the same rail at all (Razorpay's own docs confirm no workaround exists yet) — offer an alternate payment method (UPI/different card) instead.
- `insufficient_funds` / `expired_card` → standard bounded retry with backoff.
- Retry cap: e.g. max 3 attempts with backoff at 24h / 72h / 7 days (mirrors RBI's 24-hour pre-debit notice rule).
- Stopping rule: after max attempts or a fixed window, mark unrecoverable and log why — don't retry indefinitely.

## 8. Orchestrator architecture — the agentic core
This is the component the buildathon actually means by "agent," so build it deliberately rather than defaulting to if/else.

**How it works**: at each decision point, call the LLM with the classified failure, full attempt history, and promise-to-pay status. The LLM reasons about the situation and responds by choosing exactly one tool call from this fixed set:

```
request_stepup()        — sends step-up approval on the SAME mandate_id
offer_alternate_method() — the only tool ever exposed for rupay_hard_block
schedule_retry()         — internally refuses to fire past the retry cap
send_notification()      — drafts and logs the Hinglish message
escalate_human()         — hands off, logs why
mark_recovered()
mark_unrecoverable()     — logs the reason for the record
```

**Where the safety lives**: not in restricting what the LLM is allowed to *think*, but in what each tool is allowed to *do*. `schedule_retry` is hard-capped in code regardless of what the LLM asks for. `rupay_hard_block` cases are never even given a retry tool to call. No tool can move money or contact a customer outside these bounds. This is exactly what the track means by "bounded recovery workflow" — genuine reasoning, hard rails.

**Free audit trail**: log the LLM's reasoning text alongside every tool call it makes. That reasoning *is* your audit trail entry — richer than a static log line, and something you can put on screen live during the demo ("here's why the agent escalated this one instead of retrying").

## 9. What the demo must show (this is the track's actual bar)
- **Measured recovery rate**: run the compliant-flow agent and the naive/broken-flow baseline against the *same* synthetic batch, report % and ₹ recovered by each. The gap between them is your pitch.
- **One failure handled gracefully** — pick one (e.g. `rupay_hard_block`) and show the agent correctly declining to retry and escalating instead, rather than hammering a dead end.
- **A visible audit trail** — every decision traceable, not just a final number.
- **Honest exceptions** — report what the agent could *not* recover and why, don't cherry-pick the wins.

## 10. Suggested tech stack
Python backend · Razorpay Python SDK (test mode) for the real API plumbing · a plain rule engine for classification (resist the urge to make this an ML model — the rule is a regulation, not a pattern to learn) · **Claude Haiku via the Anthropic API as the default LLM** for the orchestrator's tool-calling reasoning and notification drafting (cheap and fast enough to call per-event across the whole batch) · **Ollama running a small local model (e.g. Llama 3.1 8B) as a documented fallback** — no dependency on live internet or API rate limits during the actual judged demo · FastAPI for the backend · Streamlit for a live demo dashboard showing decisions, audit log, and metrics · SQLite or JSON for the audit store.

## 11. Metrics to compute and display
- Batch size and breakdown by failure category
- Recovery rate: compliant-flow % vs naive-flow % (and the ₹ amounts behind each)
- Time-to-recovery (average)
- Unresolved/escalated count with reasons

## 12. Deliverables checklist
- Public GitHub repo, clean README (problem, architecture, how to run, headline metrics)
- Architecture diagram (a mermaid diagram in the README is fine)
- requirements.txt / setup instructions
- The synthetic dataset (or its generator script) committed for reproducibility
- 5-minute pitch video: open with the real documented merchant complaint → show compliant-vs-broken flow → live demo → the recovery-rate delta → the audit trail → one gracefully-handled failure

## 13. Guardrails — tell the agent this explicitly
- Every money-affecting decision must be logged and explainable — no unexplained agent actions.
- Compute the recovery-rate numbers from actual synthetic batch runs. Never hardcode or approximate the headline metric.
- Show the failure case, don't hide it — a demo with zero visible failures reads as cherry-picked, not robust.
- Keep classification and orchestration in separate, inspectable modules so any decision can be explained on demand during the panel.
- The LLM in the orchestrator chooses *which* tool to call and reasons about *why* — but never gains a capability the tool set doesn't expose. Don't add a tool that lets the LLM retry indefinitely, move money outside the defined flows, or skip the audit log. If a new capability is needed later, add it as a new bounded tool, not as freeform LLM output.