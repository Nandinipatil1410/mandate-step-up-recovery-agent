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
