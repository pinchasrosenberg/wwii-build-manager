# Economy, pricing and fidelity investment

There are two ledgers: buyer spending/obligations and provider capital/costs. A research token reservation from the existing Driver store is not a sale price. Internal simulated credits have no USD conversion. Production money is integer minor units with explicit currency and rounding; mixed currencies require an explicit conversion quote. No floating point balance arithmetic.

## Lifecycle

`EVALUATED → QUOTED → RESERVED → ACCEPTED → EXECUTING → DELIVERED → RESULT_VALIDATED → ACTUAL_COST_RECORDED → SETTLED`. Cost may arrive earlier, but settlement requires independent result acceptance against frozen quote criteria and reconciled cost. Partial/rejected work follows frozen failure terms. Order acceptance differs from result acceptance.

Quote binds request digest, capability version, scope, artifacts/quality acceptance criteria, fixed price, currency, expiry, cancellation/failure terms, evaluation reference and provider identity. A quote cannot change after acceptance. Changing scope produces a new quote and separate authorization. Reserve atomically holds the buyer's quoted price; Accept checks expiry, identity, digest, authorization and reservation. Paid execution cannot begin before Accept. Paid evaluation/listening itself needs a prior umbrella quote; evaluation is not a loophole for spending before quoting.

Let price be P and actual cost be C. On successful settlement buyer pays P exactly; provider records revenue P, cost C and profit P−C. If C<P, surplus belongs to provider. If C>P, provider capital absorbs the difference. Example in synthetic credits: quote 100, actual 130, buyer pays 100, provider loses 30. Cancellation, failed delivery and refunds follow frozen terms; do not charge full success price for a failed result unless that failure service was explicitly purchased. A provider must have bounded execution exposure/reserve or decline the work; speculative future revenue cannot make today's liability disappear.

Buyer invariant: `available = funded − settled_spend − active_holds`, never negative. Provider: capital+settled revenues−actual costs−active risk commitments must remain within its explicitly authorized credit limit. Holds are not spent twice; a parent/child allocation has one financial owner. Settlement, cost receipt and reservation release are atomic and idempotent. Unknown actual usage remains null/RECONCILE rather than zero. Outbox delivery cannot duplicate charges.

## PricingEvaluation

Record expected_cost, cost_uncertainty, P50/P75/P95, risk_reserve, expected_demand, reuse_value, future_revenue, historical_value, player_visibility, quality_gain (vector), accuracy_gain and strategic_value. Values are estimates with calibration window, units, model/rule version and assumptions. Require P50≤P75≤P95. Percentiles must be derived from a distribution or explicitly labeled uncalibrated estimates; three arbitrary numbers are not measured risk.

Provider can mark up, discount, subsidize or accept a temporary loss within its capital policy. Evaluation and quote price are different objects: the buyer is not charged provider's evolving estimates. Track realized vs predicted cost/quality and reuse over time. Do not bill the same model usage again as both tokens and an equivalent combined compute unit.

## FidelityPlanner

Hard constraints first: no strong historical contradiction, evidence integrity, legal asset availability, equipment identity agreement, usable performance, context policy and required experience gates. Then compare investments across the nine quality dimensions. Candidate includes cost, expected accuracy/visual/simulation/character/atmosphere/gameplay gains, historical importance, visibility, reuse, uncertainties, dependencies and measurable success criterion.

An illustrative heuristic is weighted expected gain + reuse value − cost − risk; historical importance×uncertainty reduction×reuse×visibility/cost is usable only when units/scales and zero-cost handling are defined. It is not a universal maximization theorem. Use Pareto alternatives when incomparable gains matter. Improving uniforms cannot displace a known wrong vehicle correction. Once historical gates pass, sound or companion animation may deliver more experience value than extra geographic detail.

Investment selection reserves money, builds assets/claims, validates, then publishes a new immutable Episode revision. Capital does not automatically raise a confidence tag. Evidence review changes certainty; playtests change experience estimates. Negative results can still be valuable if they prevent a bad reconstruction.

## Maturity and validation

M0 local simulator is planned to prove a subset of fixed-price lifecycle with test credits. Durable concurrent accounting, real external costs, liability policies, provider authentication, quote signing, tax/payment processing and live marketplace learning remain later work. Production gate includes double-reservation races, duplicate settlement, conflicting retries, expiry, stale input, cancel-after-send, uncertain costs, crashes before/after receipt and refund policy tests. A process-local dictionary demonstration is never described as a financial ledger ready for use.

Production quotes must reference a bounded result-review deadline and reconciliation deadline in their frozen terms. The quote acceptance service rejects missing terms. At a deadline, escalate to the named reconciliation owner; do not change P, retry uncertain work, or silently release unknown exposure. Agreed refund/failure terms determine disposition. M0 has no durable deadline worker or dispute service, so this gate is explicitly unmet for real funds.
