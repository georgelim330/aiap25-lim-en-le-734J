# Travelers' Inn Booking Fall-Through Risk

**AIAP Batch 25 Technical Assessment**

- **Full name (as in NRIC):** Lim En Le
- **Email used in the AIAP application:** georgelim330@gmail.com

## 1. Project title

Travelers' Inn Booking Fall-Through Risk: a leakage-safe, temporally evaluated classifier and revenue-at-risk prioritisation pipeline.

## 2. Business problem

Travelers' Inn loses room revenue when confirmed bookings are cancelled or become no-shows. The operational need is an early, ranked view of risky reservations so revenue and reservation teams can decide where reconfirmation, reminders, policy review, or waitlist attention may be worthwhile. The system must not assume extra staff or room capacity.

## 3. ML problem definition

The pipeline predicts whether a confirmed reservation will **fall through**:

- `1`: final status is `Canceled` or `No-Show`;
- `0`: final status is `Check-Out` (an honoured stay).

Scoring uses only information reasonably available when a booking is confirmed. The output is a probability, not an automatic intervention. A secondary score prioritises bookings by:

```text
potential_booking_value = ADR x total booked nights
expected_revenue_at_risk = predicted fall-through probability x potential_booking_value
```

Expected revenue at risk is a prioritisation indicator. It is not a claim that the amount is recoverable.

## 4. Repository structure

```text
.
|-- .github/workflows/github-actions.yml  # Official assessment workflow
|-- data/hotel.db                         # Local only; ignored by Git, fetched on demand
|-- scripts/build_eda.py                  # SOURCE of eda.ipynb: rebuilds and executes it
|-- src/
|   |-- __init__.py
|   |-- config.py                         # Bounded model-search settings
|   |-- data.py                           # Read-only SQLite load, validation, cleaning, split
|   |-- evaluate.py                       # Metrics, threshold, deciles, business summary
|   |-- features.py                       # Booking-time feature engineering and leakage boundary
|   |-- main.py                           # CLI and end-to-end orchestration
|   |-- models.py                         # Dummy, logistic, and boosted candidates
|   `-- preprocessing.py                  # Train-fitted sklearn transformations
|-- tests/                                # 19 synthetic unit, isolation, and end-to-end tests
|-- artifacts/                            # Generated model bundle; ignored
|-- reports/                              # Generated metrics/plots/predictions; ignored
|-- README.md
|-- decision_log.md                       # Official template; candidate completes it
|-- decision_log_evidence.md              # Evidence notes, not final answers
|-- eda.ipynb
|-- prompt_chat_history.md                 # Official template; raw transcript required
|-- requirements.txt
`-- run.sh
```

## 5. Setup

Python 3.12 or newer is required (`numpy==2.5.2` declares `requires-python >=3.12`). Python 3.12.10 was used for local validation. From the repository root:

```bash
python -m venv .venv
```

Activate the environment, then install the declared dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Dataset

The assessment forbids committing `hotel.db`, and the supplied GitHub Actions workflow only checks out the repository, installs `requirements.txt`, and runs `run.sh`. A checked-out copy therefore has no database. The pipeline resolves this itself: if `data/hotel.db` is absent it downloads the published dataset from

```text
https://techassessment.blob.core.windows.net/aiap25-assessment-data/hotel.db
```

using the Python standard library only (no extra dependency, and nothing is installed at run time). The download is written to a temporary file, validated as a SQLite database containing both required tables, and only then moved into place, so an interrupted or corrupted fetch cannot leave a half-written `data/hotel.db` behind. If you already have the file, put it at `data/hotel.db` and no network call is made. Pass `--no-download` to fail fast instead of fetching.

The database is ignored by both the `data/*.db` and `*.db` rules and must never be uploaded.

## 6. How to run

The assessment entry point is:

```bash
bash run.sh
```

Equivalent direct command:

```bash
python -m src.main --data data/hotel.db
```

A clean run takes about 21 seconds after the dataset is available.

The run prints a concise summary and generates:

- `reports/metrics_summary.json`
- `reports/validation_results.csv`
- `reports/test_predictions.csv` (no email field)
- `reports/risk_deciles.csv`
- `reports/cleaning_report.json`
- `reports/leakage_audit.csv`
- evaluation and explanation plots
- `artifacts/fall_through_model.joblib`

`eda.ipynb` is generated, not hand-edited. `scripts/build_eda.py` is its source: it constructs every cell, executes the notebook against a real kernel, and writes the executed result. Edit the script, not the notebook, or changes are overwritten on the next rebuild:

```bash
python scripts/build_eda.py
```

Run tests with:

```bash
python -m pytest -q
```

The suite covers ingestion, cleaning rules, feature construction, model-pipeline robustness to unseen categories and missing numerics, and two guards on the evaluation protocol specifically: one asserts that inverting every 2025 outcome leaves the validation table, the selected model, and the selected threshold bit-for-bit identical; the other records the row count of every `fit` call to prove the final model is refitted on the 48-row development set and never on the full frame.

## 7. Configuration

Useful CLI options are visible through `python -m src.main --help`. Examples:

```bash
bash run.sh --logistic-c 0.1 0.5 1.0
bash run.sh --hgb-learning-rate 0.05 0.1 --hgb-max-leaf-nodes 15 31
bash run.sh --hgb-max-iter 100 --hgb-l2-regularization 0.5 --random-state 25
bash run.sh --one-hot-min-frequency 50
bash run.sh --train-year 2023 --validation-year 2024 --test-year 2025
bash run.sh --skip-importance --no-plots
bash run.sh --data /path/to/hotel.db --no-download
```

Every value in `SearchConfig` (`src/config.py`) is reachable from the command line, as are the split years, the output directories, and the dataset source. `SearchConfig` is a frozen dataclass that validates its own arguments, so an invalid search space fails immediately rather than part-way through a run.

The HistGradientBoosting grid is capped at nine combinations to prevent accidental, expensive searches. The default run evaluates seven candidates: one dummy, two logistic, and four boosted configurations.

## 8. Dataset overview

SQLite integrity passed. The source has two tables:

| Table | Source rows | Columns | Intended grain |
|---|---:|---:|---|
| `bookings` | 118,549 | 36 | One reservation row |
| `reviews` | 17,583 | 3 | One submitted review row |

All SQLite columns are declared as `TEXT`; no database primary or foreign key is enforced. After removing 353 exact duplicate booking rows, 118,196 unique reservations remain. The final cleaned target has 43,028 fall-throughs (36.40%).

Arrival coverage is 1 August 2023 to 31 August 2025, and the calendar blocks are unevenly shaped:

| Block | Role | Arrival months present | Rows | Fall-through rate |
|---|---|---|---:|---:|
| 2023 | Train | August–December only | 19,193 | 35.86% |
| 2024 | Validation | January–December | 58,384 | 34.96% |
| 2025 | Final test | January–August only | 40,619 | 38.74% |

This has a consequence the pipeline cannot remove: **the training block contains no January–July arrivals at all**, while the test block is entirely January–August. The cyclic `arrival_month_sin` / `arrival_month_cos` features are therefore fitted on autumn/winter arrivals and must extrapolate across a half-year the model never saw in training. It also means the training and test blocks differ in season *and* in year, so the two effects cannot be separated with this data. Month-of-arrival effects reported below should be read as descriptive, and the split is defensible mainly because it is chronological, not because the blocks are comparable.

## 9. Data quality and preprocessing

Cleaning is deterministic and produces `reports/cleaning_report.json` with affected-row counts.

| Observed issue | Rule | Rows affected after exact deduplication | Justification |
|---|---|---:|---|
| Exact duplicate bookings | Keep one byte-equivalent row | 353 removed | Prevent double-counting; conflicting duplicate IDs fail closed |
| Mixed target booleans | Map `0/false/No` to 0 and `1/true/Yes` to 1 | 2,327 source strings normalised | Verified against final status with zero mismatches |
| Malformed `lead_time` | Coerce to missing | 50 | Train-fitted median imputation follows; see the caveat below |
| Negative `lead_time` | Set to missing and retain missingness flag | 300 | Negative advance notice is impossible at confirmation |
| Malformed `adr` | Coerce to missing | 318 | Train-fitted imputation follows; see the caveat below |
| Category case/spelling variants | Map observed variants to documented canonical values | e.g. country 5,780; deposit 1,074; segment 868 | Avoid fragmenting equivalent categories |
| Missing/malformed supplied arrival week | Do not use supplied week | 490 source rows | The field also disagrees with the validated date on 63,722 source rows |
| Zero-night / zero-guest bookings | Retain with explicit flags | 625 / 187 after deduplication | Could be day-use or unresolved source issues; deletion would be speculative |
| Duplicate/invalid reviews | Deduplicate for context and exclude from predictors | 51 duplicate rows; 173 ratings outside 1-5 | Reviews are post-stay and not part of the model |

**Caveat on the two "coerce to missing" rules.** Those 368 values are not genuinely unreadable — they are format variants: a European decimal comma (`276,00`), a currency prefix (`SGD 253.00`), and a unit suffix (`14 days`). A parsing rule recovers every one of them. Treating them as missing is a real, if small, loss of information (0.27% of rows), and it also zeroes their `potential_booking_value`. It was left in place because changing a model input after the holdout has been scored would require re-running selection and re-reporting the final metrics; see Limitations and Future work. The `adr_missing` and `lead_time_missing` indicator features at least let the model see that the value was absent rather than silently accepting an imputed median.

Numeric imputation, scaling, one-hot encoding, and ordinal encoding are fitted inside sklearn pipelines on training data only. Because every transformer lives inside the `Pipeline`, `fit` is called on the training block alone and `transform` is applied to validation and test — there is no path by which a statistic from a later period can reach an earlier fit.

## 10. Leakage controls

| Feature | Decision | Availability time | Leakage rationale |
|---|---|---|---|
| Export index, `booking_id` | Drop | Dataset creation / booking | No predictive business meaning; memorisation risk |
| `client_email` | Drop | Booking | Direct identifier and privacy risk |
| `is_canceled` | Target validation only | Final outcome | Direct label |
| `reservation_status` | Target construction only | Final outcome | Direct final outcome |
| `reservation_status_date` | Drop | Final outcome | Timestamp of final status |
| `assigned_room_type` | Drop | Check-in | Not known at confirmation |
| `booking_changes` | Drop | Through cancellation/check-in | Accumulates post-scoring information |
| Rating, comments, review presence | Drop | Post-stay | Reviews appear only for Check-Out rows and reveal the outcome |
| Agent/company raw identifiers | Transform to presence flags | Booking | Known, but high-cardinality and operationally unstable |
| Waiting days, deposit, promo, reserved room, ADR, nights | Keep | Confirmation | Booking terms known at scoring time |
| Prior booking history | Keep | Booking | Explicitly predates the current outcome |

The full machine-readable table is regenerated at `reports/leakage_audit.csv`. The final feature matrix contains 37 booking-time predictors and no target/post-outcome field.

## 11. Feature processing table

| Feature group | Processing | Models |
|---|---|---|
| Lead time, ADR, nights, guests, history, requests, parking, waiting days | Parse numeric; impossible negatives become missing; median imputation fitted on training | Logistic and boosted |
| Numeric features for logistic regression | RobustScaler after training-only imputation | Logistic |
| Low-cardinality categories | Canonical string mapping; missing becomes `Missing`; infrequent-aware one-hot encoding | Logistic |
| Low-cardinality categories | Canonical mapping; unknown-safe ordinal encoding; categorical mask supplied to estimator | HistGradientBoosting |
| Arrival date | Derive cyclic month and weekday sine/cosine; do not use inconsistent supplied week | Logistic and boosted |
| Stay composition | `total_nights`, `total_guests`, `weekend_share` | Logistic and boosted |
| Booking economics | `potential_booking_value = ADR x total_nights` | Logistic and boosted |
| Source availability | `has_agent`, `has_company`, `has_promo_code` | Logistic and boosted |
| Ambiguous edge cases | `zero_night_booking`, `zero_guest_booking`, `lead_time_missing`, `adr_missing` | Logistic and boosted |

## 12. EDA summary

Detailed questions, charts, explanations, business implications, and leakage evidence are in `eda.ipynb`. Development-period highlights (2023-2024 only) include:

- 27,294 of 77,577 bookings fell through (35.2%).
- City Hotel fall-through was 39.8% versus 26.0% for Airport Hotel.
- Risk rose from 9.9% for 0-7-day lead time to 76.6% for 366+ days.
- Group bookings had 60.6% fall-through versus 14.9% for Direct bookings.
- Non-refundable bookings had a counter-intuitive 99.2% fall-through rate, signalling strong selection/policy association rather than a causal effect. This single field carries most of the model's discriminative power, which is a risk as much as a result.
- Reviews linked only to honoured stays: all 17,532 bookings with a matching review are `Check-Out`, a 0.0% fall-through rate against 42.7% for the 100,664 bookings without one. Review presence is therefore a perfect leak of the target and is excluded, along with rating and comments.
- `client_email` is unique across all 118,196 bookings, so no guest appears in more than one period and the chronological split cannot leak a repeated customer across blocks.
- The 2023 training block covers August–December only, so seasonal features extrapolate at test time (section 8).

These findings motivated simple booking-time interactions and a nonlinear boosted model, while retaining logistic regression as an interpretable benchmark.

## 13. Model selection

The chronological protocol is:

```text
2023 train (19,193)
    -> 2024 validation: model + parameter + threshold selection (58,384)
    -> freeze decisions
    -> refit selected configuration on 2023+2024 (77,577)   <-- threshold is carried across
    -> 2025 final test, scored once (40,619)
```

No test metric is used to select a feature, model, hyperparameter, or threshold. Validation average precision is the selection metric because ranking positive bookings matters and the positive class is not balanced. Brier score breaks an exact average-precision tie.

The refit step is deliberate — it gives the deployed model four times the training data — but it is also where the threshold problem in section 14 originates, because the frozen cut-off was derived from the smaller model. `tests/test_main.py` pins both halves of this protocol: one test proves that inverting every 2025 outcome changes nothing that is decided before the freeze, and another records the row count of every `fit` call to prove the final model sees the 48-row development set and never the full frame.

| Best candidate per family (2024 validation) | ROC-AUC | Average precision | Brier | F1 at validation-selected threshold |
|---|---:|---:|---:|---:|
| Dummy most-frequent | 0.5000 | 0.3496 | 0.3496 | 0.0000 |
| Logistic Regression (`C=1.0`) | 0.7622 | 0.7210 | 0.1929 | 0.6060 |
| HistGradientBoosting (`lr=0.1`, leaves=31) | **0.7984** | **0.7558** | 0.1893 | 0.6283 |

The selected boosted model captures nonlinearities and interactions while staying within scikit-learn, avoiding a compiled external dependency such as LightGBM. Validation permutation importance is led by deposit type, country, parking request, prior cancellations, lead time, and special requests. Importance is association, not causation. Logistic coefficient direction is saved separately for an interpretable comparison.

## 14. Evaluation metrics and rationale

- **ROC-AUC:** ranking quality across thresholds.
- **Average precision / PR-AUC:** ranking quality focused on the fall-through class.
- **Precision:** share of flagged bookings that actually fall through; relates to workload efficiency.
- **Recall:** share of all fall-throughs captured; relates to missed opportunities.
- **F1:** balanced threshold objective because intervention costs/capacity are unavailable.
- **Confusion matrix:** operational false-positive and false-negative counts.
- **Brier score:** squared probability error; important for risk/value calculations.
- **Calibration curve:** checks predicted versus observed risk by probability band.
- **Accuracy:** reported for completeness, not used for selection.

The threshold (0.03718) maximised F1 on 2024 validation only, where precision was 61.4% and recall 64.3%. A cost- or capacity-optimal threshold cannot be estimated without intervention and workload data.

### A known weakness: the threshold does not transfer to the refitted model

The protocol selects the threshold from a model trained on **2023 only** and then applies that same absolute number to a model refitted on **2023+2024**. Those are different models, and a probability cut-off is a property of the model that produced the probabilities, not a portable constant. Enlarging the training set sharpens the probability distribution, so the same cut-off lands in a different place.

This was measured inside the development period, with no use of the 2025 block. Holding the scored period fixed at July–December 2024 and changing only the training set:

| Training set | Rows | Share flagged at 0.03718 | Own max-F1 threshold |
|---|---:|---:|---:|
| 2023 only | 19,193 | 31.1% | — |
| 2023 + Jan–Jun 2024 | 48,095 | 45.0% | 0.02072 |

Training-set size alone moves the flagged share by 14 percentage points, and the better-trained model's own optimal threshold is roughly half the transferred one. The final model is trained on 77,577 rows, a larger jump still.

**What this means for the numbers in section 15.** ROC-AUC, average precision, Brier score, and log loss are threshold-free and are unaffected. Precision (0.4940), recall (0.9862), F1 (0.6583), accuracy (0.6033), and the confusion matrix are *not* — they describe an operating point that was tuned for a different model. They are reported honestly, because the threshold was frozen before 2025 was touched and re-picking it now would consume the holdout. They should be read as "what this frozen rule happened to do", not as a validated operating point. The threshold-free ranking metrics and the risk-decile table in section 16 are the trustworthy evidence of model quality.

The clean fixes all require a protocol change and therefore a fresh, unused holdout: derive the threshold from out-of-fold probabilities produced by the same training regime as the final model, or score 2025 with the 2023-only model so that model and threshold match, or calibrate on a separate block before choosing a cut-off. Each is listed in Future work rather than applied here.

## 15. Final results

Final 2025 results for the frozen selected configuration:

| Metric | Result |
|---|---:|
| ROC-AUC | 0.8675 |
| Average precision | 0.8237 |
| Brier score | 0.1493 |
| Log loss | 0.4473 |
| Precision | 0.4940 |
| Recall | 0.9862 |
| F1 | 0.6583 |
| Accuracy | 0.6033 |
| True negatives | 8,990 |
| False positives | 15,895 |
| False negatives | 217 |
| True positives | 15,517 |

### Calibration is biased in a specific direction

The Brier score of 0.1493 compares with 0.2373 for a model that always predicts the base rate, a Brier skill score of **0.371**. But the error is not symmetric noise — the model systematically **under-predicts** risk:

| Mean predicted | Observed | Gap |
|---:|---:|---:|
| 0.0018 | 0.0007 | −0.001 |
| 0.0485 | 0.1425 | **+0.094** |
| 0.0980 | 0.2093 | **+0.111** |
| 0.1545 | 0.2802 | **+0.126** |
| 0.2328 | 0.3667 | **+0.134** |
| 0.3790 | 0.4798 | +0.101 |
| 0.6253 | 0.6305 | +0.005 |
| 0.8252 | 0.7378 | −0.087 |
| 0.9987 | 1.0000 | +0.001 |

Across the whole test block, mean predicted risk is 0.3376 against an actual rate of 0.3874 — a **5.0 percentage-point global under-prediction**. Part of this is expected: the model is trained on 2023–2024, where the fall-through rate is 35.0%, and scored on 2025, where it is 38.7%. The extremes (near 0 and near 1) are well calibrated; the middle of the range is not.

This matters directly for section 17, because expected revenue at risk is `probability x value`. **The reported S$13.55M is therefore biased low**, most severely for the mid-risk bookings that make up the bulk of the portfolio. Treat it as a conservative floor for ranking purposes, not an estimate of exposure. No calibration model was fitted at any point, on any period — fitting one now would require a block that has not been used.

The very broad threshold flag (77.3% of test bookings) is explained in section 14 and is a property of the transferred threshold, not of the model's ranking quality.

## 16. Business interpretation

At the validation-F1 threshold:

- 31,412 of 40,619 test bookings are flagged;
- precision among flagged bookings is 49.4%;
- recall of fall-throughs is 98.6%;
- average predicted risk among flagged bookings is 43.4%.

This operating point is recall-heavy and too broad for a small manual team. It is reported because it was frozen before the test block was touched, not because it is recommended.

Four separate questions are easy to conflate, so they are kept apart here:

1. **Ranking quality** — can the model order bookings by risk? Yes: ROC-AUC 0.8675, average precision 0.8237, and a strictly monotone decile profile. This is the model's actual claim.
2. **Threshold choice** — where to cut the ranking. Answered by maximising validation F1 in the absence of cost data, and, as section 14 explains, it did not transfer to the refitted model.
3. **Operational capacity** — how many bookings a team can actually work per day. Not in the dataset. This, not F1, should set the cut in production.
4. **Intervention policy** — what to do with a flagged booking, and whether it changes anything. Requires a controlled experiment; nothing here speaks to it.

**The decile view is the better operational illustration**, and it is threshold-independent, so it is unaffected by the weakness in section 14:

| Risk decile | Bookings | Observed fall-through | Lift | Cumulative recall |
|---:|---:|---:|---:|---:|
| 1 | 4,062 | 100.0% | 2.58x | 25.8% |
| 2 | 4,062 | 73.8% | 1.90x | 44.9% |
| 3 | 4,062 | 63.0% | 1.63x | 61.1% |
| 4 | 4,062 | 48.0% | 1.24x | 73.5% |
| 5 | 4,062 | 36.7% | 0.95x | 83.0% |
| ... | | | | |
| 10 | 4,061 | 0.07% | 0.00x | 100.0% |

A team with capacity for the top 10% of arrivals reaches bookings that fall through essentially every time; the top 30% captures 61% of all fall-throughs. The bottom decile is near-empty of risk, which is operationally as useful — it identifies bookings that can safely be left alone. A capacity-based top-N or percentile queue expresses this directly and avoids depending on a fixed probability constant, but it must still be validated prospectively before use.

Note that decile 1 is close to a restatement of `deposit_type = Non Refund`, which alone runs at 99.35% fall-through and covers about a tenth of bookings. The model's incremental contribution is clearest in deciles 2–5, where it separates risk within the No Deposit population.

Suggested actions remain hypotheses: targeted reconfirmation, reminder/contact workflows, deposit/policy review, and waitlist prioritisation. Controlled overbooking requires separate capacity, displacement-cost, and safety analysis.

## 17. Revenue-at-risk prioritisation

For the final test period:

- total potential booking value: **S$39,071,434.54**;
- probability-weighted expected revenue at risk: **S$13,550,911.73**;
- flagged potential booking value: **S$31,051,618.32**;
- flagged expected revenue at risk: **S$13,477,791.03**.

All amounts are in Singapore dollars, matching the `adr` field, which the data dictionary defines as the average daily rate in SGD.

These amounts rank exposure. They do not estimate causal revenue uplift or net benefit. Actual value depends on successful contact, customer response, replacement demand, intervention cost, and unintended effects.

Four specific caveats on the arithmetic:

- **The probability factor is biased low.** See section 15: mid-range probabilities under-predict observed risk by 9–13 percentage points, so these totals understate exposure.
- **The value factor is unbounded and long-tailed.** `potential_booking_value` is raw `ADR x nights` with no winsorising; ADR ranges from 0 to 7,108 SGD, and 1,229 bookings exceed 1,000 SGD per night. A single mis-keyed rate moves the total.
- **Some bookings contribute zero by construction.** 515 test bookings have a value of 0 — 625 bookings across the dataset have zero booked nights, and bookings whose ADR could not be parsed are treated as missing and contribute nothing (117 such rows in the test block, worth roughly S$118,000 of recoverable value; see Limitations).
- **Negative and missing values are floored at zero** before summing, so the totals are lower bounds rather than signed exposure.

## 18. Deployment architecture and considerations

```text
booking confirmed
    -> schema and range validation
    -> versioned feature transformation
    -> versioned model probability
    -> probability + expected-value priority
    -> reservation/revenue dashboard or work queue
    -> intervention outcome logging
```

- **Batch vs online:** daily/hourly batch scoring is simplest for a work queue; online scoring is suitable if immediate booking workflows justify the added reliability burden.
- **Do not ship the frozen threshold.** Section 14 shows that 0.03718 belongs to a model trained on 19,193 rows and does not survive a refit. Any deployment must re-derive its operating point from the deployed model's own out-of-sample probabilities, or use a capacity-based top-N queue, which sidesteps absolute cut-offs entirely.
- **Versioning:** store model, feature contract, training window, threshold, dependency versions, and Git SHA together — and treat the threshold as bound to a specific trained model, not as a configuration constant that outlives it.
- **Monitoring:** input missingness/categories, population drift, output drift, delayed-label ROC/AP, Brier/calibration, threshold workload, and segment performance.
- **Retraining:** begin with a quarterly review; retrain only when enough labelled data and monitored degradation justify it.
- **Logging:** retain booking ID, timestamp, model/version, features or validated feature hash, probability, threshold decision, and eventual outcome. Do not log email into model artifacts.
- **Privacy:** keep `client_email` outside the model and restrict any operational contact lookup to authorised systems.
- **Experiments:** record whether and how staff intervened, then use controlled experiments before claiming reduced fall-through or revenue uplift.

## 19. Limitations

- **The threshold was selected for a different model than the one it is applied to** (section 14). The thresholded test metrics are honest but describe an unvalidated operating point; the ranking metrics and decile table are the sound evidence.
- **The training block has no January–July arrivals** (section 8), so seasonal features extrapolate at test time and season cannot be separated from year effects.
- **Probabilities under-predict risk by about 5 percentage points overall** and by 9–13 points mid-range (section 15), which biases the revenue-at-risk totals low.
- **318 ADR values and 50 lead-time values are discarded although they are recoverable.** The malformed tokens are a European decimal comma (`276,00`), a currency prefix (`SGD 253.00`), and a unit suffix (`14 days`); a simple parsing rule would recover all 368. They are currently coerced to missing and median-imputed, and the affected bookings contribute zero potential value. This was left unchanged deliberately: repairing it alters model inputs, which would require re-running model and threshold selection and consuming the 2025 holdout to report new figures.
- **Model performance is dominated by one near-deterministic rule.** `deposit_type = Non Refund` has a 99.35% fall-through rate overall (99.74% / 98.88% / 99.81% by year) and accounts for about a tenth of bookings — almost exactly the top risk decile, whose observed rate is 100.0%. This is a booking-time field so it is not leakage, but the headline ROC-AUC leans on it, and the underlying commercial mechanism should be confirmed with stakeholders before it is trusted prospectively.
- The source gives no intervention costs, staffing capacity, replacement demand, or causal treatment outcomes.
- Raw agent/company identity is intentionally excluded; presence flags may lose useful stable partner information.
- Zero-night, zero-guest, extreme ADR, and extreme lead-time records remain unresolved source-system questions.
- Reviews cannot support early prediction and need a separate post-stay analysis.
- The `no-show` outcome has only 1,179 rows and is pooled with cancellations; the two may warrant different interventions.

## 20. Future work

1. **Fix the threshold procedure on a fresh block.** Derive the cut-off from out-of-fold probabilities produced by the same training regime as the deployed model, so model and threshold match. Validate on a period not yet used; 2025 is now spent.
2. Collect intervention type, cost, outcome, replacement demand, and staff capacity, then define the operating point from expected net value or an explicit top-N capacity rather than F1.
3. **Recover the parseable ADR and lead-time values** (European decimal commas, `SGD` prefixes, `N days` suffixes — 368 rows in total) and re-run selection and evaluation end to end on a new holdout, reporting the change rather than substituting the figures.
4. Add prospective calibration monitoring and evaluate sigmoid/isotonic calibration on a later, separate time block, given the measured 5-point under-prediction.
5. Test deposit/channel stability by future cohort and investigate the operational mechanism with stakeholders, given how much of the headline performance rests on one field.
6. Add a validated booking-event timestamp and rolling/expanding temporal backtests, which would also remove the partial-year seasonality confound.
7. Run controlled experiments before claiming causal reduction in fall-through or revenue improvement.

## 21. AI assistance and the written deliverables

Three assistants were used in distinct roles, and `prompt_chat_history.md` carries the record:

| Tool | Role | Transcript |
|---|---|---|
| ChatGPT (web) | Assessment interpretation, problem framing, comparison of the three candidate ML problems, leakage reasoning | Share link + transcript pasted by the candidate |
| OpenAI Codex (agent mode) | Implementation: EDA notebook, `src/` pipeline, tests, training and evaluation run, README draft | Exported verbatim from the local Codex session log; no share-link feature |
| Claude Code (agent mode) | Independent adversarial review of the finished submission, then final submission preparation | Exported verbatim from the local Claude Code session log; no share-link feature |

Both agent transcripts are the literal on-screen conversation, exported from the session logs the tools write to disk. Tool calls, command output, and the models' internal reasoning traces are excluded — they are not conversation, and the reasoning traces were never user-visible. Nothing was reworded, shortened, or reordered. One redaction is noted inline: the candidate's full NRIC, which appeared once.

`decision_log.md` is the candidate's own writing. `decision_log_evidence.md` is a separate working file of verified facts, alternatives, and trade-offs gathered during the build and review; it exists so the Decision Log could be written against evidence rather than recollection, and it is not itself a deliverable.

## Reproducibility note

All reported numbers above come from the generated files in `reports/` produced by the default deterministic command. Generated outputs are gitignored so the submission stays small; rerun `bash run.sh` to reproduce them, including on a clean clone with no local dataset. Do not commit `data/hotel.db`.

The run is deterministic: repeating it regenerates `metrics_summary.json`, `validation_results.csv`, `test_predictions.csv`, `risk_deciles.csv`, `cleaning_report.json`, `review_quality.json`, `leakage_audit.csv`, and `permutation_importance.csv` byte-for-byte. Every random seed flows from the single `--random-state` value.
