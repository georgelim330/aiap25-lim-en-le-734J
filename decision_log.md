# AIAP Technical Assessment — Decision Log

**Candidate name (as in NRIC):** Lim En Le

**Email (as used in your application):** georgelim330@gmail.com

---

## A note on this document

This decision log is the primary instrument by which we understand your thinking. The questions below cover the reasoning behind your work — from how you define the problem at the start to the decisions you made during the work itself. Do answer all five questions in your own words. 

You may use AI assistance freely on the technical deliverables (the EDA and the ML pipeline), but this Decision Log itself should be written by you — it is the record of your own thinking that we cross-check against your chat history.


---

## 1. Clarifying questions

What questions would you ask to better define and narrow the problem statement? For each question, briefly explain how the answer would meaningfully change your approach. 

Note: If it helps your decision-making, you may assume and list out the stakeholders' likely answers.


**Your answer:**

Nobody actually answered these, so everything below is a question I would put to the Head of Revenue & Reservations plus the assumption I ended up working under. I have tried to be clear about which is which, because several of my modelling choices are only defensible under the assumption I picked.

**At what point in the booking lifecycle does scoring happen?** This is the single most important one, because it decides what counts as a legitimate feature. If we score at confirmation, then `days_in_waiting_list` and the deposit terms are fair game but anything updated later is not. If we score nightly right up to arrival, I could use how the booking has changed over time, which is a much richer signal. I assumed **scoring at confirmation**, and that assumption is what forced me to throw away `booking_changes` and `assigned_room_type` — both are strong predictors but both keep updating after the moment I claim to be predicting from.

**What can Reservations actually do with a high-risk booking, and how many can they handle a day?** A model that flags 31,000 bookings is useless to a team of three people. Without a capacity number I have no principled way to pick a cut-off, which is exactly the weakness I ended up with (see Q3). If they told me "we can call 200 bookings a day", I would have built a top-N queue instead of a probability threshold, and the whole evaluation section would look different.

**What is the relative cost of a false positive versus a missed cancellation?** Contacting a guest who was always going to show up costs a few minutes and a small annoyance risk. Missing a cancellation on a high-value room costs a night's revenue. If someone gave me even a rough ratio, I could optimise expected cost instead of F1. I had no such number, so I fell back on F1, which implicitly treats precision and recall as equally important — that is a modelling convenience, not a business fact.

**What is the actual KPI — occupancy, net revenue, or staff efficiency?** These pull in different directions. Protecting occupancy favours high recall. Protecting net revenue means weighting by booking value, which is why I added the revenue-at-risk score. Staff efficiency favours precision. I assumed a **prioritisation** objective: rank bookings so a limited team looks at the right ones first.

**Which fields will genuinely exist in the production system at booking time?** The dataset I was given is a historical export, and an export is not a live feed. If `agent` or `country` is often blank at the moment of booking and only filled in later, my offline numbers are optimistic. I assumed the booking-time fields are populated as they appear here, and flagged it as something to confirm with the source-system owners before anything is deployed.

**Should cancellations and no-shows be treated as one outcome?** They are commercially different — a cancellation two months out is recoverable inventory, a no-show is a dead night. I pooled them because there are only **1,179** no-shows against 41,849 cancellations after deduplication, which is too thin to model separately with any confidence. But if the intervention differs, that pooling is wrong and I would want to know early.

**Is overbooking on the table, and under what constraints?** The brief says room and staff expansion is out of the question, which makes controlled overbooking an obvious lever. But it needs walk-cost and displacement analysis I have no data for, so I deliberately did not go near it.

**Is pricing work actually wanted, and what other data exists?** The Head of Revenue mentioned pricing explicitly, so I would want to know whether they have inventory, competitor rates, or any record of demand they turned away — because without those, a pricing model is not really possible (see Q2).

---

## 2. Defining the Problem Statement

Restate, in your own words, the refined problem you decided to solve. List your key assumptions. Briefly note what other framings you considered, and what you deliberately left out or scoped down, and why.


**Your answer:**

**The problem I chose to solve:** using only information reasonably available when a booking is confirmed, estimate the probability that the booking will fall through — that is, end as a cancellation or a no-show rather than an honoured stay — and turn that probability into a ranked work queue for the Reservations team, weighted by how much money each booking represents.

The brief named three possible angles — fall-throughs, pricing, and mixed customer feedback — and asked for the best one. I looked at what the data could actually support for each.

**Fall-through prediction (chosen).** There are 118,196 usable bookings after cleaning, with a clean binary outcome and a **36.40%** positive rate, so this is not a rare-event problem where I would be fighting for signal. The target is unambiguous: `reservation_status` is one of `Check-Out`, `Canceled`, or `No-Show`, and it agrees with the `is_canceled` flag on every single row once I normalised the six different spellings in that column. Most importantly, the prediction happens *before* arrival, which means there is a window in which someone could actually act. It maps directly onto "we lose a lot of rooms at the last minute and we rarely see it coming."

**Dynamic pricing (rejected).** This was the tempting one because the stakeholder mentioned it first, but the data does not support it. `adr` is the rate the hotel actually charged — it is a record of their existing pricing behaviour, not a label for what the *right* price would have been. Training a model to predict ADR would just teach it to imitate the current gut-feel pricing, which is the thing she is unhappy with. To do this properly I would need room inventory, competitor rates, demand that was turned away, and some way to estimate elasticity. None of that is in the two tables. I would rather say this cleanly than produce a pricing model that looks impressive and means nothing.

**Review and satisfaction modelling (rejected, and it turned into a leakage finding).** There are only 17,583 reviews against 118k bookings, and they are all post-stay, so they cannot inform a pre-arrival decision. Then I joined them to the bookings and found something more interesting: **every single one of the 17,532 bookings with a matching review is a `Check-Out`.** The reviewed group has a 0.0% fall-through rate against 42.7% for the 100,664 bookings without a review. So the mere existence of a review perfectly reveals the outcome. That is the most dangerous feature in this dataset — it would have produced a near-perfect model that predicts nothing — and it is why rating, comments, and review presence are all excluded from the feature set entirely.

**Key assumptions:**

1. Scoring happens at confirmation; anything that updates after that is off-limits.
2. Cancellations and no-shows share an initial operational response, so one label is acceptable for a first version.
3. The model outputs a probability for a human to act on. It does not take any action itself.
4. Associations in this data are not causal. Non-refundable bookings cancelling 99% of the time does not mean deposits cause cancellations.
5. `potential_booking_value` (ADR × nights) is a reasonable proxy for what a booking is worth, even though it ignores replacement demand.

**Deliberately scoped out:** pricing optimisation, review sentiment/NLP, a separate no-show model, overbooking policy, and any attempt to estimate how much revenue an intervention would actually save. That last one matters — I can rank exposure, but I cannot tell you what you would recover by acting on it, because there is no record in this data of anyone ever intervening.

---

## 3. Key decisions during Solution Development

Walk through three key decisions you made during Solution Development. For each: what options did you consider, what did you choose, and why? These can be technical (modelling choices, feature handling, evaluation metrics) or about the work itself (what to prioritise, what to drop, how to spend your time).


**Your answer:**

### Decision 1 — Drawing the leakage boundary by availability time, not by intuition

The first version of my exclusion list was basically a guess: drop the obvious target fields and move on. I replaced that with a rule — for every column, ask *when does this value become known?* — and then checked each answer against the data instead of trusting my reasoning.

That check changed my mind three times. `reservation_status_date` looked harmless until I differenced it against the arrival date: honoured stays average **+3.3 days** (checkout is after arrival) while fall-throughs average **−85.9 days**. The sign alone gives the answer away. `assigned_room_type` is only set at check-in, and sure enough, bookings where it differs from the reserved type fall through 5.5% of the time against 40.7% otherwise. `booking_changes` keeps accumulating right up to cancellation, and bookings with any change fall through 15.6% versus 40.1%. All three would have inflated my metrics while being unavailable at the moment I claim to predict.

The one I nearly got wrong was reviews, which I covered in Q2.

I also had to decide what to do with `agent` (332 distinct IDs) and `company` (240). The options were one-hot encoding, target encoding, or reducing them. High-cardinality identifiers are exactly where a boosted tree memorises individual partners, and travel agencies come and go, so a model keyed to specific agent IDs would decay quietly. I reduced both to `has_agent` / `has_company` presence flags. That is a real loss — a genuinely reliable corporate partner is now indistinguishable from a flaky one — and I would revisit it with a proper time-aware encoding if I had longer.

On cleaning: I removed 353 exact duplicate rows, but only after checking that every repeated `booking_id` was byte-identical. The code raises an error if two rows share an ID but differ, because silently keeping one of two conflicting records is the kind of thing that corrupts an analysis invisibly. I also normalised the target column, which contains `0`, `1`, `true`, `false`, `Yes`, and `No` — 2,327 rows use a non-numeric spelling — and then cross-checked the normalised flag against `reservation_status` on all 118,196 rows. Zero disagreements, which gave me confidence the label is trustworthy.

### Decision 2 — Chronological split and a deliberately small model search

I split by arrival year: 2023 to train (19,193), 2024 to select on (58,384), 2025 as an untouched final test (40,619). A random split would have been easier and would have given better-looking numbers, but it would let the model learn from 2025 booking patterns to predict 2024 — which is not a situation that exists in production. A chronological split is the honest one.

It is not a clean split though, and I want to be upfront about it. The data runs 1 Aug 2023 to 31 Aug 2025, so **2023 only contains August–December arrivals and 2025 only contains January–August.** My training block therefore contains no January-to-July arrival at all, and my test block is almost entirely made of them. The cyclical month features I built are extrapolating into a half-year the model has never seen, and I cannot separate seasonal effects from year-on-year drift with this data. I kept the split anyway, because the alternative — shuffling — trades a visible limitation for an invisible one.

For models I ran a `DummyClassifier` as a floor, logistic regression at two regularisation strengths as an interpretable baseline, and `HistGradientBoostingClassifier` across four configurations. Seven candidates total. I could have thrown a wide grid search at it, but with a single fixed validation year every extra configuration is another chance to overfit that one year, and the marginal gain is small. HGB won on validation average precision (0.7558 against 0.7210 for the best logistic), so I took it.

I chose **average precision** as the selection metric rather than accuracy or ROC-AUC because the job is ranking the positive class, and at a 36% base rate accuracy would reward a model that just predicts "honoured" for everything. I tracked **Brier score** alongside it because I multiply the probability by a dollar value later, so the probability needs to be roughly right and not just well-ordered.

I stayed inside scikit-learn rather than adding LightGBM or XGBoost. HGB is a histogram-based booster in the same family and performs comparably here; adding a compiled dependency to satisfy a GitHub Actions runner I cannot test against felt like an unnecessary risk for a marginal gain.

### Decision 3 — How to express business value, and what I chose not to fix afterwards

I wanted output the Revenue team could act on, so alongside the probability I compute `potential_booking_value = ADR × nights` and `expected_revenue_at_risk = probability × potential_booking_value`. Across the 2025 block that totals **SGD 13,550,911.73**. I am deliberately careful with how I describe that figure: it ranks exposure. It is not money the hotel would get back, because nothing in this data records anyone ever intervening, so I have no basis at all for an uplift claim.

For the operating threshold I maximised F1 on the 2024 validation year, which gave 0.037177. On validation that is a balanced point — 61.4% precision, 64.3% recall. On the 2025 test it behaves completely differently: 49.4% precision, 98.6% recall, and it flags 77.3% of all bookings, which is far too broad for a real team.

**This is the weakest part of my submission and I want to explain it rather than bury it.** The threshold came from a model trained on 2023 alone, but the model that actually scores 2025 was refitted on 2023+2024. Those are different models and a probability cut-off is not portable between them. I checked this using only development data — holding the scored period fixed at the second half of 2024, a model trained on 19,193 rows flags 31.1% at that threshold while one trained on 48,095 rows flags 45.0%, and the larger model's own best threshold is roughly half the original. So training-set size alone moves the operating point substantially.

I found this **after** I had already scored 2025. I chose not to re-pick the threshold, because re-picking it now would mean using the final test set to make a modelling decision, and then my reported test metrics would no longer be an honest holdout. I would rather submit a known, documented weakness than a better-looking number I cannot defend. The practical consequence is stated in the README: ROC-AUC (0.8675) and average precision (0.8237) are threshold-free and stand on their own, but the precision/recall/F1/accuracy figures describe an operating point that was never properly validated. The decile table is the view I would actually put in front of the business.

The same reasoning applies to a data-cleaning defect I found late. 318 `adr` values and 50 `lead_time` values fail to parse, and I had been treating them as missing — but when I looked at the actual tokens they are all mechanically recoverable: European decimal commas (`276,00`), a currency prefix (`SGD 253.00`), and a unit suffix (`14 days`). Every one of the 368 would parse under a simple rule. Fixing it would change the model's inputs, which means re-running selection and re-scoring the holdout to report new numbers. For 0.27% of rows, that is not worth spending the only clean test period I have. It is documented as a known limitation and it is the first item in my future work.

---

## 4. Use of the AI assistant

Where did you use the AI assistant in this work? Give three specific examples of something the assistant suggested that you changed, rejected, or significantly modified — and explain your reasoning.


**Your answer:**

I used AI heavily and I want to be straightforward about how much. Three tools, in three distinct roles.

**ChatGPT (web)** for thinking before building: interpreting the assessment brief, arguing through which of the three business angles was actually supportable by the data, reasoning about what counts as leakage, and planning the order of work.

**Codex** as the implementation agent, working directly in the repository: profiling the database, generating the EDA notebook, writing the `src/` pipeline modules and tests, running the training and evaluation, and drafting the README.

**Claude Code** as an independent adversarial reviewer afterwards, with instructions to verify rather than trust — re-reading the assessment PDF from scratch, auditing the target and leakage boundary independently, testing reproducibility, and critiquing the threshold and calibration work.

Splitting implementation and review across two tools was deliberate. An agent that wrote the code is a poor judge of whether the code is right, and giving the reviewer explicit permission to contradict the implementer surfaced things I would otherwise have submitted.

**Three things I changed or rejected:**

**1. I rejected the pricing framing that came out of my first ChatGPT conversation.** The initial suggestion was to build an ADR regression model, since pricing was the first thing the stakeholder complained about and `adr` is right there as a numeric column. I pushed back once I thought about what the column actually is: it is the price the hotel charged, not the price they should have charged. A model trained on it learns to reproduce the gut-feel pricing that is causing the problem. I asked what data a real pricing model would need — inventory, competitor rates, turned-away demand, elasticity — confirmed none of it exists in these two tables, and moved to fall-through prediction instead.

**2. I rejected a "drop the obvious leakage columns" list and replaced it with an availability-time audit.** The assistant's first pass gave me a sensible-looking exclusion list, and it would have been easy to accept. But it was reasoning from column names, not from the data. I turned it into a rule — when does each value become known? — and then verified each call against the actual numbers. That is how I caught the review-presence leak, which was not on the original list at all and is the most severe one in the dataset. It also changed two calls in the other direction: `days_in_waiting_list` is known at confirmation so I kept it, and `agent`/`company` became presence flags rather than being dropped outright.

**3. I did not accept Codex's "everything passes" report at face value, and the independent review found three real problems.** Codex reported 14 passing tests and a clean run. Claude, reviewing independently, found that **`bash run.sh` fails on a clean checkout** — the dataset is correctly gitignored, and the supplied GitHub Actions workflow only does checkout, install, run, so the assessment's own CI would have failed on my submission. That is fixed now: the pipeline fetches the published database if it is not present locally, using only the standard library so `requirements.txt` does not change. The same review challenged the threshold transfer described in Q3, which I had not spotted, and found the recoverable `adr` and `lead_time` values. I also added tests rather than trusting the existing pass count — in particular one that inverts every 2025 outcome and asserts that nothing chosen before the final scoring step changes, and one that records the row count of every `fit` call to prove the final model never trains on the test block. I checked both of those actually fail when I deliberately break the pipeline, because a test that cannot fail is not evidence.

**What I am not claiming:** most of the implementation code was written by Codex, and I directed and reviewed it rather than typing it myself. The problem framing, the leakage rule, the decision to keep the chronological split despite its flaws, and the decision not to re-tune the threshold after seeing 2025 are mine. The specific engineering — the module layout, the sklearn pipeline construction, the plotting code — largely is not.

---

## 5. Next Steps

If you had one more week to continue this project, what would you do next, and why? What signals from your current work make those the right next steps?


**Your answer:**

**First, fix the threshold properly on data I have not already spent.** This is the clearest known defect. The evidence is in Q3: training-set size alone shifts the flagged share from 31% to 45% at the same cut-off. The fix is to derive the operating point from out-of-fold predictions produced by the same training regime as the deployed model, so the threshold and the model actually match — and to validate that on a period I have not scored, since 2025 is now used up.

**Second, sit down with Reservations and get the two numbers I was missing.** How many bookings can they realistically contact per day, and what does a wasted contact cost relative to a missed cancellation. With those, the threshold stops being an F1 artefact and becomes a capacity or expected-cost decision. My guess is the answer is a top-N queue rather than a probability cut-off, which would also sidestep the transfer problem entirely.

**Third, deal with the calibration gap before anyone leans on the money figure.** On 2025 the model predicts a mean risk of 0.3376 against an actual rate of 0.3874, and the mid-range bins are off by 9 to 13 percentage points. Since revenue-at-risk is probability × value, that pattern means the SGD 13.55m figure may well be understated — though I would not present it as a guaranteed floor either, because it is a prioritisation indicator and the calibration could move in a different period. I would evaluate isotonic or sigmoid calibration on a separate untouched block, not on anything already used.

**Fourth, get more complete years.** The seasonal gap in Q3 is a data problem, not a modelling one. Two or three full calendar years would let me use rolling or expanding backtests instead of one fixed three-way split, and would separate season from year-on-year drift.

**Fifth, understand the deposit-type result before trusting it.** Non-refundable bookings fall through **99.35%** of the time and make up about a tenth of all bookings — almost exactly my top risk decile, which sits at a 100.0% observed rate. That single field carries roughly four times the permutation importance of the next one. It is known at booking so it is not leakage, but a near-deterministic rule usually means a business process rather than customer behaviour, and I would want to know what it is before betting on it holding next year.

**Sixth, the smaller cleanups:** recover the 368 malformed `adr` and `lead_time` values (ideally fixed upstream at the source system so the export stops producing three different number formats), and set up drift and calibration monitoring so degradation is caught by a dashboard rather than by someone noticing the queue looks wrong.

**And the thing I would not do yet:** claim any revenue impact. Nothing in this data records an intervention ever happening, so there is no way to estimate what acting on these predictions achieves. That needs a controlled experiment — flag bookings, act on a random half, compare — and until that runs, everything here is prioritisation and nothing more.

---
