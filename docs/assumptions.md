# Checkpoint 1 assumptions

1. **Money uses integer paise.** Exactly ₹15,000 is `1_500_000`; an “above ₹15,000” rule uses strict greater-than comparison.
2. **Payment rail and card network are separate.** `payment_rail` is `card` or `upi`. `card_network` is present only for card records.
3. **INR only.** The regulatory scenario is INR-specific, so checkpoint 1 does not generate other currencies.
4. **Mandate identifiers are not universally UMRNs.** Every record has a provider-neutral `mandate_id`; `umrn` is nullable.
5. **Expired cards use the brief's bounded-retry action label.** A later workflow should notify the customer to update the card before retrying, but checkpoint 1 does not invent an eighth tool outside section 8's fixed tool set.
6. **Unknown failures escalate.** The `other` category maps to `escalate_human` rather than an automated money-affecting action.
7. **Attempt numbering includes the current failed debit.** `attempt_number` equals the number of stored previous attempts plus one.
8. **The recovery window defaults to seven days.** This is stored on each record for later stopping-rule scenarios.
9. **Recoverability is probabilistic synthetic ground truth.** Rates in `config/generator.toml` create a mixed evaluation batch. They are assumptions, not claimed production recovery rates.
10. **Ground truth is an answer key.** Runtime modules receive `to_runtime_dict()` output, which excludes category, correct action, and recoverability labels.

The generator uses a fixed UTC base time rather than the current clock. This makes byte-for-byte reproducibility possible for a given configuration, seed, and count.

## Checkpoint 2 rule precedence

When observable signals conflict, the classifier applies this explicit order:

1. RuPay above the configured hard threshold;
2. recognized insufficient-funds decline code;
3. recognized expired-card decline code;
4. non-RuPay amount above its mandate ceiling;
5. explainable `other` fallback.

The RuPay constraint comes first because a recurring debit above the threshold cannot proceed on that rail regardless of another decline signal. Explicit issuer decline codes then take precedence over inferred mandate-ceiling failure because they state the observed cause more directly. This precedence is configurable only through reviewed code/config changes, never by an LLM.

## Checkpoint 3 simulation and agent assumptions

1. The full offline batch defaults to `scripted`, clearly recorded as `deterministic-policy-v1`. It exercises the same context, permission, tool-validation, execution, and audit-trace path as an LLM without requiring credentials or network access.
2. Groq and Ollama are optional decision providers. A missing or invalid provider fails closed; the application does not silently invent a money-affecting decision.
3. Model “reasoning” means a short auditable decision summary supplied with the tool call, not hidden chain-of-thought.
4. AFA-compliant execution preserves `mandate_id`; the naive baseline deliberately creates a simulated replacement mandate.
5. RuPay hard-block cases receive only `offer_alternate_method` on their initial agent turn. Direct retry execution is independently rejected too.
6. `mark_recovered` is the only tool available after verified payment evidence. `mark_unrecoverable` is the only tool available after a verified terminal condition.
7. Success probabilities in `config/recovery.toml` are transparent synthetic assumptions. Both strategies use the same deterministic latent customer response per transaction, while strategy-specific probabilities model intervention effectiveness.
8. The initial comparison is one recovery intervention per transaction. Multi-turn scheduling, notifications, promise follow-up, and complete lifecycle audit are checkpoint 4.

## Checkpoint 4 lifecycle and integration assumptions

1. **Three attempts means the original failed debit plus two retries.** The
   retries occur after 24 hours and then 72 hours. The brief's “7 days” is
   interpreted as the outer recovery window, because three total attempts leave
   only two retry intervals.
2. **The simulated clock is authoritative for offline evaluation.** No test waits
   in real time. Retry notices are emitted at the calculated notice timestamp,
   and retries at the calculated execution timestamp.
3. **A promise without a confirmed payment becomes missed when due.** The tracker
   sends one follow-up and then refuses another. A real deployment would consume
   a payment-status signal before making that transition.
4. **Notification generation does not contact customers.** It drafts and audits
   text only. A basic output validator rejects requests for OTP, PIN, CVV, or full
   card details even when an LLM provider produced the text.
5. **The audit chain is tamper-evident, not an immutable database.** Each event
   hashes its complete content and the previous event hash. Production should
   additionally store it in access-controlled, durable infrastructure.
6. **Groq is the demo LLM provider.** The deterministic scripted provider remains
   the reproducible evaluator and fail-safe path. Groq receives runtime-visible
   evidence only and cannot enlarge its permitted tool set.
7. **Razorpay is an optional test-mode edge integration.** The client refuses
   non-`rzp_test_` keys. Subscription lookup, alternate-method Payment Link
   creation, and verified webhook normalization demonstrate realistic plumbing;
   synthetic events continue to model the bank-side defect.
8. **A Razorpay Payment Link is not represented as same-mandate AFA.** Until an
   applicable test-mode API can prove that operation, `request_stepup` remains a
   transparent simulation tied to the existing mandate ID. This avoids claiming
   that a new payment or mandate is the compliant step-up flow.
