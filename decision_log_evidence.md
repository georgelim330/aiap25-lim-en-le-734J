# Decision Log Evidence Notes

This file is **not** a completed Decision Log. It contains factual evidence, implemented decisions, alternatives, trade-offs, limitations, and prompts for the candidate's own reasoning. The five official questions remain unchanged and unanswered in `decision_log.md`.

## 1. Clarifying questions

### Factual evidence available

- The business request names cancellations, no-shows, pricing, and reviews but does not specify an operational user, action, workload capacity, intervention cost, or success criterion.
- Dataset coverage is 1 August 2023 to 31 August 2025; the first and last years are partial.
- Final outcomes are 43,028 fall-throughs among 118,196 deduplicated bookings (36.40%).
- The validation-F1 threshold flags 77.3% of 2025 bookings, showing why staff capacity and intervention cost materially affect threshold choice.
- Reviews link only to honoured stays and therefore cannot be used for early-risk prediction.

### Questions the candidate should answer in their own words

- At what exact booking lifecycle event will scoring occur: creation, payment, or confirmation?
- Which team owns the output, how many bookings can it review per day, and what action can it take?
- What are the costs of contacting a low-risk guest, missing a fall-through, offering an incentive, or holding inventory?
- Are deposit type and channel policy set before scoring, and can they change later?
- Should cancellations and no-shows receive the same intervention, or only the same initial model label?
- What business outcome defines success: fewer fall-throughs, higher occupancy, net revenue, staff efficiency, or calibrated risk?
- What do zero-night, zero-guest, extreme ADR, and extreme lead-time rows mean operationally?
- What privacy and retention rules apply to booking identifiers and client email?

## 2. Defining the Problem Statement

### Evidence and implemented decision

- Implemented task: binary classification at booking confirmation.
- Positive target: final `Canceled` or `No-Show`; negative target: `Check-Out`.
- Normalised `is_canceled` and final status agree on all deduplicated rows.
- Operational output: probability plus `probability x ADR x total nights` prioritisation.
- Expected revenue at risk is explicitly not treated as recoverable revenue.

### Alternatives considered

- ADR regression / price optimisation: not selected because no demand, competitor-price, inventory, elasticity, or causal pricing data is present.
- Review sentiment/NLP: not selected because reviews are post-stay, sparse relative to bookings, and outcome-revealing.
- Separate cancellation and no-show multiclass model: not selected because no-show has only 1,179 deduplicated rows (41,849 Canceled, 75,168 Check-Out) and the initial operational response may be shared.
- Unsupervised segmentation: useful for discovery, but less directly actionable than an early booking-risk queue.

### Trade-offs and limitations

- Combining cancellation and no-show improves support but may hide different causes and interventions.
- Confirmation-time scoring permits waiting-list duration but excludes fields updated through check-in/cancellation.
- Classification supports prioritisation but does not estimate causal intervention impact.

## 3. Key decisions during Solution Development

### Decision evidence: leakage boundary

- Dropped: export index, booking ID, email, final target/status/date, assigned room, booking changes, reviews, rating, comments, review presence.
- Transformed: agent/company raw identifiers become presence flags.
- Kept: confirmed booking terms, reserved room, ADR, nights, deposit, promo, waiting days, and prior history.
- Trade-off: conservative drops reduce leakage and instability but may remove legitimate late-booking information.

### Decision evidence: temporal evaluation

- Train: 2023 (19,193 rows).
- Validation/model/parameter/threshold selection: 2024 (58,384 rows).
- Final test: 2025 (40,619 rows).
- Alternative rejected: random split, because it mixes future booking patterns into training.
- Limitation: partial-year coverage makes the calendar blocks unequal and can mix seasonality with drift.

### Decision evidence: model set and selection

- DummyClassifier establishes prevalence/no-skill behavior.
- Logistic Regression provides an interpretable linear probability baseline.
- HistGradientBoosting captures nonlinearities/interactions without an extra compiled dependency.
- LightGBM was considered but not used because scikit-learn-only installation is simpler for the provided GitHub Actions workflow.
- Selection metric: 2024 average precision; Brier breaks an exact tie.
- Best validation AP: HGB 0.7558; logistic 0.7210; dummy 0.3496.
- Selected HGB parameters: learning rate 0.1, max leaf nodes 31.

### Decision evidence: threshold

- F1 was chosen because intervention costs and staff capacity are unavailable.
- Threshold 0.03718 came only from 2024 validation: precision 61.4%, recall 64.3%, F1 62.8%.
- 2025 behavior is recall-heavy: precision 49.4%, recall 98.6%, flagged share 77.3%.
- Trade-off: the threshold is reproducible but likely impractical for a small queue; a future threshold needs explicit cost/capacity inputs and prospective monitoring.

### Decision evidence: the threshold does not transfer to the refitted model

- The threshold was chosen from a model fit on 2023 only, then applied to a model refit on 2023+2024. A probability cut-off belongs to the model that produced the probabilities.
- Measured within the development period, scoring H2-2024 in both cases: a 2023-only fit (19,193 rows) flags 31.1% at 0.03718; a 2023+H1-2024 fit (48,095 rows) flags 45.0% at the same value, and its own max-F1 threshold is 0.02072.
- Consequence: the 2025 precision/recall/F1/accuracy and confusion matrix describe an operating point never validated for the model that produced them. The threshold-free metrics (ROC-AUC, AP, Brier, log loss) and the decile table are unaffected.
- This was left unfixed on purpose. Re-deriving the threshold is a protocol change, and reporting the resulting figures would require a holdout that has not already been scored.

### Decision evidence: calibration direction

- Mean predicted risk 0.3376 versus actual 0.3874 on the test block, a 5.0-point under-prediction; mid-range quantile bins under-predict by 9 to 13 points; the 0.83 band over-predicts by 8.7 points.
- Brier skill score against an always-base-rate model is 0.371.
- Because expected revenue at risk is probability times value, the S$13.55M total is biased low.
- No calibration model has been fitted on any period.

### Decision evidence: recoverable values that are currently discarded

- All 318 malformed ADR tokens and all 50 malformed lead-time tokens parse cleanly under a simple rule: European decimal comma (`276,00`), currency prefix (`SGD 253.00`), unit suffix (`14 days`).
- They are currently coerced to missing and median-imputed; 117 of them fall in the test block and contribute roughly S$118,000 of potential booking value as zero.
- Left unchanged because recovering them alters model inputs, which would require re-running model and threshold selection and re-scoring the holdout.

### Decision evidence: what the model's performance actually rests on

- `deposit_type = Non Refund` has a 99.35% fall-through rate (99.74% in 2023, 98.88% in 2024, 99.81% in 2025) across 14,356 bookings, roughly a tenth of the data.
- Permutation importance on validation puts deposit_type at 0.197 average-precision decrease, about four times the next feature (country, 0.055).
- The top test risk decile is 4,062 bookings at a 100.0% observed rate, close to a restatement of that one field.
- The field is known at booking, so this is not leakage, but it means headline discrimination leans heavily on a single policy variable whose commercial mechanism is unexplained.

### Decision evidence: seasonal coverage of the split

- 2023 covers 1 August to 31 December; 2024 is complete; 2025 covers 1 January to 31 August.
- The training block therefore contains no January-July arrivals, while the test block is entirely January-August.
- Cyclic month features are fitted on autumn/winter arrivals and extrapolate at test time; season and year effects cannot be separated with this data.

## 4. Use of the AI assistant

### Auditable examples to consider when writing the candidate's own answer

- Working suggestion: prefer a fall-through classifier over ADR prediction. Result: accepted only after validating target support and identifying the lack of price-elasticity/demand data.
- Working suggestion: use LightGBM if robust. Result: modified to sklearn HistGradientBoosting to reduce GitHub Actions dependency risk while retaining a strong nonlinear model.
- Working suggestion: mechanically exclude a likely leakage list. Result: changed into an explicit availability-time audit; waiting days were kept at confirmation, agent/company became presence flags, and reviews were excluded after the actual join proved outcome-revealing.
- Working suggestion: use latest year as final test. Result: accepted after confirming actual date coverage, with the partial-year caveat and a chronological 2023/2024/2025 protocol.
- Assistant implementation choice: validation-F1 threshold. Result to critique: transparent and test-independent, but its 77.3% final-period workload shows that missing cost/capacity inputs matter.
- Assistant-generated EDA/pipeline code was checked by executing the notebook, running synthetic tests, running the real pipeline, comparing README figures with generated reports, and visually inspecting plots.

### Questions for the candidate's own response

- Which suggestions were actively challenged rather than accepted?
- Which implementation detail was changed after checking the real data?
- What evidence was independently inspected before trusting AI-produced code or prose?
- Which remaining AI-produced assumption would need stakeholder confirmation?

## 5. Next Steps

### Signals from current work

- Strong ranking: final ROC-AUC 0.8675 and AP 0.8237.
- Imperfect calibration in middle risk bands; Brier 0.1493.
- Broad operating point: 31,412 of 40,619 test bookings flagged.
- Concentrated ranking: top decile has 2.58x lift and captures 25.8% of fall-throughs.
- Dominant deposit-type importance could reflect policy/channel selection rather than a stable causal mechanism.
- No intervention, capacity, cost, replacement-demand, or causal outcome data exists.

### Candidate-owned next-step choices to justify

- Collect intervention type, cost, staff capacity, contact success, guest response, replacement demand, and eventual net revenue.
- Define a capacity- or expected-net-value threshold instead of F1.
- Validate calibration on a later untouched block; consider sigmoid/isotonic calibration only with a separate calibration period.
- Add rolling or expanding temporal backtests once booking timestamps and more history are available.
- Investigate deposit/channel stability with source-system and revenue stakeholders.
- Run a controlled experiment before claiming fewer fall-throughs or revenue uplift.
- Consider separate cancellation/no-show models only after enough no-show data and distinct actions exist.
