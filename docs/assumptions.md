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
