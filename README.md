# FreightTiger Smart Shipping Cost Assistant

An autonomous, production-grade AI assistant that monitors freight shipping costs across Indian transport corridors, detects unjustified rate spikes, retrieves operational real-world context notes (RAG), and explains findings in plain English with strict zero-hallucination guardrails.

Built for the **FreightTiger Software Engineering Intern (AI) 24-Hour Case Study**.

---

## 1. Problem Overview

Freight transportation costs naturally vary with distance and payload. Over time, rates can quietly creep upward. Sometimes this rise is driven by genuine, verifiable operational causes (e.g., severe flood detours, festival surcharges, diesel price hikes); other times, it is an unjustified carrier markup.

This assistant automates the detection and explanation process:
1. Ingests raw multi-transporter shipment records.
2. Groups records by corridor (`origin-destination`) and provided length tier (`Short`, `Medium`, `Long`).
3. Tracks normalized cost per tonne-km week-by-week ($w$ runs Monday to Sunday).
4. Computes exact mathematical comparison baselines:
   - **vs. Own History:** The route's trailing 8-week rolling average cost per tonne-km strictly prior to the current week (no lookahead, no padding).
   - **vs. Similar Routes:** The same-week average cost per tonne-km across all other corridors sharing the same `route_type`, strictly excluding the route itself.
5. Employs a Retrieval-Augmented Generation (RAG) engine to inspect operational context notes.
6. Enforces guardrails so that every "justified" verdict cites the exact note and verifies corridor, time window, and causal cost impact. Unsubstantiated rises are flagged for human review.
7. Provides an interactive plain-English Q&A interface for supply chain analysts.

---

## 2. Key Deliverables & Files

| File | Description |
|---|---|
| [`output.csv`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/output.csv) | Primary deliverable matching `sample_output_format.csv` exact contract schema |
| [`full_weekly_metrics.csv`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/full_weekly_metrics.csv) | Comprehensive metrics for all 728 route-weeks (auditing dataset) |
| [`planning.md`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/planning.md) | Technical blueprint, mathematical definitions, and architectural decisions |
| [`run_pipeline.py`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/run_pipeline.py) | Main executable pipeline with CLI query support and reproducibility flags |
| [`reproducibility_check.py`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/reproducibility_check.py) | Standalone script verifying 100% bitwise identity across 3 untouched runs |
| [`reproducibility_report.md`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/reproducibility_report.md) | Checksum and pairwise diff verification across 3 runs |
| [`tokencost_summary.json`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/tokencost_summary.json) | Machine-readable token and financial cost accounting |
| [`tokencost_summary.md`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/tokencost_summary.md) | Formatted token consumption and cost report |
| [`src/`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/src/) | Modular Python codebase (`core`, `rag`, `llm`, `cli`) |
| [`tests/test_pipeline.py`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/tests/test_pipeline.py) | Comprehensive pytest test suite (9 test cases, 100% passing) |

---

## 3. Mathematical Baselines (As Specified in Brief)

### 3.1 Unit Cost Formula
For each corridor and week:
$$\text{cost\_per\_tonne\_km} = \frac{\sum \text{freight\_cost\_inr}}{\sum (\text{quantity\_tonnes} \times \text{distance\_km})}$$
This represents the true volume-weighted freight rate.

### 3.2 Trailing 8-Week Own History (`vs_own_history`)
- Trailing window: up to 8 calendar weeks **strictly prior** to `week_of` (indices $w-8$ to $w-1$).
- **No lookahead:** Current week and future weeks are excluded.
- **Early week handling:** If fewer than 8 prior weeks exist (e.g. week 3 has only weeks 1 and 2), the engine averages all available prior weeks without padding or extrapolation.
$$\Delta_{\text{own}} = \frac{\text{cost}_w - \text{avg\_prior\_8}}{\text{avg\_prior\_8}} \times 100\%$$
- Formatted as: `+XX.X% vs this route's past average` (or `-XX.X%`).

### 3.3 Similar Routes Peer Average (`vs_similar_routes`)
- Peer set: All other corridors sharing the same `route_type` (`Short`, `Medium`, or `Long`) in that same week.
- **Strict self-exclusion:** The route itself is never included in its own peer average.
$$\Delta_{\text{peer}} = \frac{\text{cost}_{r, w} - \text{peer\_avg}_w}{\text{peer\_avg}_w} \times 100\%$$
- Formatted as: `+XX.X% vs similar-length routes this week` (or `-XX.X%`).

### 3.4 Anomaly Threshold Policy (Engineered Implementation Choice)
- The case study leaves the exact percentage threshold unspecified (*"Flag any route where the cost is rising and looks out of the ordinary compared to its own history or to similar routes"*).
- We implemented an explicit threshold: $\tau_{\text{own}} = 20.0\%$ OR $\tau_{\text{peer}} = 20.0\%$, with the prerequisite that cost is rising vs history ($\Delta_{\text{own}} > 0$).
- This threshold is mathematically calibrated from the three reference cases in `sample_output_format.csv` (Delhi-Jaipur at +35.5%/+21.0%, Ahmedabad-Mumbai at +29.5%/+22.5%, and Mumbai-Pune at +9.2%/+23.6%).
- Numerical calculations remain strictly independent of the justification.
- Missing history (e.g. week 1) safely yields `N/A` without generating fabricated spikes.

---

## 4. How We Convinced Ourselves It Was Right

Before submitting, we subjected the system to multiple layers of rigorous validation:

### 4.1 Exact Benchmark Calibration
We validated our calculation engine against the three sample cases provided in `sample_output_format.csv`:
1. **Delhi-Jaipur on 2024-11-11:**
   - Case study benchmark: `4.17`, `+35.5% vs this route's past average`, `+21.0% vs similar-length routes this week`, `Yes`
   - Assistant calculation: **4.17**, **+35.5%**, **+21.0%**, **Yes** (Exact match)
2. **Ahmedabad-Mumbai on 2025-01-20:**
   - Case study benchmark: `3.29`, `+29.5% vs this route's past average`, `+22.5% vs similar-length routes this week`, `No (justified)`, `N002`
   - Assistant calculation: **3.29**, **+29.5%**, **+22.5%**, **No (justified)**, **N002** (Exact match)
3. **Mumbai-Pune on 2025-09-15:**
   - Case study benchmark: `3.98`, `+9.2% vs this route's past average`, `+23.6% vs similar-length routes this week`, `Yes`
   - Assistant calculation: **3.98**, **+9.2%**, **+23.6%**, **Yes** (Exact match)

### 4.2 Strict Anti-Hallucination Guardrails
To prevent confident incorrect claims, the RAG engine implements deterministic causal filtering:
- **Corridor Match:** Note must apply to the exact corridor or `All Routes`.
- **Temporal Disruption Window:** `week_of` must fall inside the operational window of disruption.
- **Causal Cost Driver Check:** The note must describe an actual cost increase.
  - Notes stating *"costs were not significantly affected"* (`N005`) or *"absorbed without rate change"* (`N010`) are **strictly rejected**.
  - Notes stating *"affected routes not part of dataset"* (`N004`) or reporting stable/normal conditions (`N006`, `N007`, `N008`, `N009`) are **strictly rejected**.
- **No Guessing Policy:** If no genuine justification exists, `matched_note_id` is left completely blank `""`, and verdict is set to `Yes` (unexplained).

### 4.3 Automated Regression Test Suite
We created a 9-test automated pytest suite covering:
- Schema integrity and row counts (2,940 transactions, 10 notes).
- Monday-Sunday week grouping logic.
- Trailing 8-week baseline calculation with early-week handling.
- Peer group exclusion and route-type boundaries.
- Negative test cases for non-justifying notes (`N004`, `N005`, `N006`, `N007`, `N008`, `N009`, `N010`).
- Positive test cases for valid justifications (`N001` during Feb 24 - Mar 8, `N002` on Jan 20).
- Post-flood normalization (`N009` ensuring Chennai-Bangalore post-Mar 9 is not falsely justified).
- Output CSV schema and header compliance.
- 3-run reproducibility diff testing.

All 9 tests pass in **0.51 seconds**:
```bash
python -m pytest tests/ -v
```

---

## 5. Reproducibility Across 3 Untouched Runs

The evaluation guidelines require:
> *"Three untouched runs on the same input: identical flags and numbers. Explanation wording may vary; cited note, verdict, and numbers must not."*

We executed three independent passes over `shipment_records.csv`, generating `output_run1.csv`, `output_run2.csv`, and `output_run3.csv`.

### SHA256 Checksum Verification:
- **Run 1:** `e8b6b7e98bb7a956d50d5c2e6d6f3f165182cbfc14e880ddf3ae1ace22aabf74`
- **Run 2:** `e8b6b7e98bb7a956d50d5c2e6d6f3f165182cbfc14e880ddf3ae1ace22aabf74`
- **Run 3:** `e8b6b7e98bb7a956d50d5c2e6d6f3f165182cbfc14e880ddf3ae1ace22aabf74`

**Result:** **0 diffs across all 3 runs** (100% bitwise identity in numbers, flags, matched note IDs, and explanations).

---

## 6. Token Usage and Financial Cost Log

In accordance with:
> *"Sensible LLM call volume and an honest token/cost log; not unlimited spend for a fixed answer."*

By filtering candidate anomalies prior to invocation, the assistant evaluated all 728 route-weeks (2 years of operations) with only 19 targeted calls:

- **Total Invocations:** 19
- **Total Input Tokens:** 3,859
- **Total Output Tokens:** 716
- **Total Tokens:** 4,575
- **Accounting Methodology:** Offline heuristic (~3.8 characters per token) in local deterministic mode; direct provider usage metadata when live API key is configured.
- **Published Pricing Rates:** Gemini 2.5 Flash / Flash Lite ($0.075 / 1M input, $0.300 / 1M output)
- **Total Financial Cost:** **$0.000504 USD** (~INR 0.042 assuming reference rate 1 USD = 83.5 INR)

Full breakdown is documented in [`tokencost_summary.md`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/tokencost_summary.md) and [`tokencost_summary.json`](file:///c:/Users/ayush/Desktop/Ayush_rsm/Projects/TIger/tokencost_summary.json).

---

## 7. Quickstart & Usage

### 7.1 Run the Full Pipeline
Generates `output.csv`, `full_weekly_metrics.csv`, and `tokencost_summary.json`:
```bash
python run_pipeline.py
```

### 7.2 Run the 3-Run Reproducibility Verification
Executes 3 independent runs and diffs the outputs:
```bash
python reproducibility_check.py
```

### 7.3 Run the Test Suite
```bash
python -m pytest tests/ -v
```

### 7.4 Interactive Plain-English Assistant (Stretch Goal)
Ask questions directly from the command line:
```bash
python run_pipeline.py --query "Why did Chennai-Bangalore get pricier in March 2025?"
```
```bash
python run_pipeline.py --query "Why did Ahmedabad-Mumbai get pricier in January 2025?"
```
```bash
python run_pipeline.py --query "Summarize all anomalous findings"
```

Or start an interactive conversation session:
```bash
python run_pipeline.py --interactive
```

---

## 8. Summary of Findings

- **Ahmedabad-Mumbai (2025-01-20):** Cost rose to ₹3.29/tonne-km (+29.5% vs history, +22.5% vs peers). Justified by **Note N002** (regional festival week surcharge).
- **Chennai-Bangalore (2025-02-24 to 2025-03-03):** Cost spiked to ₹3.58 and ₹3.48/tonne-km (+31.5% and +22.8% vs history). Justified by **Note N001** (heavy flooding and highway detours from Feb 24 to Mar 8).
- **Chennai-Bangalore (2025-03-10 onwards):** Costs remained elevated (₹3.57/tonne-km) even though Note N001 noted roads passable by Mar 9 and Note N009 confirmed repairs completed. Correctly marked **Unexplained (`Yes`)** for human review.
- **Delhi-Jaipur (2024-11-11 to 2024-11-18):** Severe rate jump to ₹4.17/tonne-km (+35.5% vs history, +21.0% vs peers) with no matching disruption note. Flagged **`Yes`** for immediate commercial investigation.
- **Mumbai-Pune (Late 2025):** Systematic creeping rate escalation reaching ₹4.49/tonne-km (+23% to +38% higher than peer Short route Delhi-Jaipur), while industry report (Note N006) confirmed demand remained stable. Flagged **`Yes`** as potential carrier overcharging.
