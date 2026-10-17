# FreightTiger AI Case Study: Implementation Plan & Technical Blueprint

**Project:** Smart Shipping Cost Assistant  
**Author:** AI & Data Engineering Intern Candidate  
**Assessment:** FreightTiger 24-Hour AI Case Study  
**Source of Truth:** `FreightTiger_Intern_CaseStudy.pdf`, `shipment_records.csv`, `context_notes.csv`, `sample_output_format_v2.csv`  

---

## 1. Executive Summary & Objective

Companies spend millions moving freight across corridors in India. Freight costs fluctuate based on distance and payload, but can quietly creep upward either due to genuine supply-chain disruptions (fuel spikes, regional festivals, flood detours) or unjustified carrier surcharges.

The goal of this project is to build an autonomous, reliable, and production-grade assistant that:
1. Ingests raw shipment records and computes normalized cost per tonne-km week-by-week.
2. Accurately measures two strict comparative baselines:
   - **vs. Own History:** Trailing 8-week rolling average strictly before the current week (no lookahead, no padding).
   - **vs. Similar Routes:** Same-week peer average across routes in the same length tier (`Short`, `Medium`, `Long`), strictly excluding the route itself.
3. Flags anomalous cost rises that deviate from historical baselines or peer corridors.
4. Employs a Retrieval-Augmented Generation (RAG) and reasoning engine to cross-reference potential anomalies against context notes.
5. Strictly enforces guardrails against hallucination: every justified verdict must cite the exact note ID and prove route, time window, and causal cost impact; all other spikes are marked unexplained.
6. Provides an interactive plain-English Q&A interface for logistics stakeholders (stretch goal).
7. Demonstrates 100% reproducibility across 3 untouched runs, transparent token/cost accounting, and rigorous evaluation.

---

## 2. Input & Output Contract Schemas

### 2.1 Input 1: `shipment_records.csv`
- Total rows: 2,940 shipment transactions.
- Date range: `2024-01-01` to `2025-12-28` (104 calendar weeks).
- Routes (Origin-Destination):
  - `Delhi-Jaipur` (Short, ~280 km)
  - `Mumbai-Pune` (Short, ~150 km)
  - `Ahmedabad-Mumbai` (Medium, ~530 km)
  - `Chennai-Bangalore` (Medium, ~350 km)
  - `Kolkata-Bhubaneswar` (Medium, ~440 km)
  - `Delhi-Chennai` (Long, ~2,180 km)
  - `Mumbai-Delhi` (Long, ~1,400 km)
- Fields:
  - `shipment_id`: String (e.g. `SHP00001`)
  - `origin`: String (e.g. `Mumbai`)
  - `destination`: String (e.g. `Pune`)
  - `route_type`: Enum (`Short`, `Medium`, `Long`)
  - `material`: String (e.g. `Packaged Foods`, `Steel Coils`, `Textiles`, `Cement`, `Auto Parts`, `FMCG Cartons`)
  - `quantity_tonnes`: Float > 0
  - `distance_km`: Float > 0
  - `freight_cost_inr`: Float > 0
  - `shipment_date`: Date string `YYYY-MM-DD`
  - `transporter`: String (e.g. `Shivam Freight Co`, `Om Sai Transport`, etc.)

### 2.2 Input 2: `context_notes.csv`
- Total rows: 10 operational context notes (`N001` to `N010`).
- Fields:
  - `note_id`: String (e.g. `N001`)
  - `date`: Date string `YYYY-MM-DD`
  - `applies_to`: Corridor name (e.g. `Chennai-Bangalore`) or `All Routes`
  - `note`: Text describing the real-world operational event.

### 2.3 Output Contract: `sample_output_format.csv` (or `sample_output_format_v2.csv`)
Columns and ordering are strict contracts:
1. `route`: String (e.g. `Delhi-Jaipur`)
2. `week_of`: Date string `YYYY-MM-DD` (Monday of the shipment week)
3. `cost_per_tonne_km`: Float formatted to 2 decimal places (e.g. `4.17`)
4. `vs_own_history`: Percentage formatted string (e.g. `+35.5% vs this route's past average`)
5. `vs_similar_routes`: Percentage formatted string (e.g. `+21.0% vs similar-length routes this week`)
6. `flagged`: Enum string (`Yes` or `No (justified)`)
7. `matched_note_id`: Note ID string (e.g. `N002`) if justified, or blank if unexplained
8. `reason`: Plain-English explanation grounded strictly in the note or stating unexplained.

---

## 3. Mathematical Foundations & Metric Definitions

### 3.1 Week Aggregation
- Weeks run **Monday through Sunday**.
- `week_of` is defined as the Monday date (`YYYY-MM-DD`) of that shipment week.
- Grouping key: `(route, week_of)` where `route = f"{origin}-{destination}"`.

### 3.2 Unit Cost Metric
$$\text{cost\_per\_tonne\_km} = \frac{\sum_{i \in \text{group}} \text{freight\_cost\_inr}_i}{\sum_{i \in \text{group}} (\text{quantity\_tonnes}_i \times \text{distance\_km}_i)}$$
*Note:* This is the true weighted network cost per tonne-km across all shipments in the route-week, exactly as defined in the case study brief.

### 3.3 Trailing 8-Week Rolling Average (`vs_own_history`)
- Trailing window: up to 8 calendar weeks **strictly prior** to `week_of` (indices $w-8$ to $w-1$).
- **No look-ahead bias:** Current week $w$ and any future weeks are excluded.
- **Handling early weeks:** If fewer than 8 prior weeks exist (e.g. week 3 has only weeks 1 and 2), average all available prior weeks without padding or extrapolation.
$$\text{avg\_prior} = \frac{1}{K} \sum_{k=1}^K \text{cost}_{w-k} \quad (1 \le K \le 8)$$
$$\Delta_{\text{own}} = \frac{\text{cost}_w - \text{avg\_prior}}{\text{avg\_prior}} \times 100\%$$
- Formatting: `+XX.X% vs this route's past average` (or `-XX.X%`).

### 3.4 Same-Week Peer Route Average (`vs_similar_routes`)
- Peer set: All distinct routes sharing the same `route_type` (`Short`, `Medium`, or `Long`) in week $w$, **strictly excluding the route itself**.
$$\text{peer\_avg} = \frac{1}{|P|} \sum_{p \in P, p \ne r} \text{cost}_{p, w}$$
$$\Delta_{\text{peer}} = \frac{\text{cost}_{r, w} - \text{peer\_avg}}{\text{peer\_avg}} \times 100\%$$
- Formatting: `+XX.X% vs similar-length routes this week` (or `-XX.X%`).

---

## 4. Anomaly Detection & Flagging Strategy

A route-week is identified as a candidate cost anomaly when:
$$\Delta_{\text{own}} \ge \tau_{\text{own}} \quad \text{OR} \quad \Delta_{\text{peer}} \ge \tau_{\text{peer}}$$
Based on calibration with the provided sample output:
- `Delhi-Jaipur` on `2024-11-11`: $\Delta_{\text{own}} = +35.5\%$, $\Delta_{\text{peer}} = +21.0\%$
- `Ahmedabad-Mumbai` on `2025-01-20`: $\Delta_{\text{own}} = +29.5\%$, $\Delta_{\text{peer}} = +22.5\%$
- `Mumbai-Pune` on `2025-09-15`: $\Delta_{\text{own}} = +9.2\%$, $\Delta_{\text{peer}} = +23.6\%$

**Flagging Criteria & Implementation Decision:**
- The case study brief leaves the exact anomaly threshold unspecified, directing developers to: *"Flag any route where the cost is rising and looks out of the ordinary compared to its own history or to similar routes."*
- We engineered an explicit threshold policy: $\tau_{\text{own}} = 20.0\%$ and $\tau_{\text{peer}} = 20.0\%$, requiring positive rising momentum vs history ($\Delta_{\text{own}} > 0$).
- This threshold is mathematically calibrated from the three reference cases in `sample_output_format.csv` (where Delhi-Jaipur, Ahmedabad-Mumbai, and Mumbai-Pune breached 20% on one or both baselines).
- Each candidate anomaly then undergoes RAG note grounding:
  - If a valid, causally positive note matches: `flagged = "No (justified)"`, `matched_note_id = note_id`.
  - If no valid note matches or the note confirms normal/no-impact conditions: `flagged = "Yes"`, `matched_note_id = ""`.

---

## 5. RAG & Note Grounding Guardrails

### 5.1 Note Classification Matrix
| Note ID | Date | Corridor | Cost Impact? | Valid Justification? |
|---|---|---|---|---|
| **N001** | 2025-02-24 | Chennai-Bangalore | Yes (+detour costs, Feb 24 - Mar 8) | **VALID** for Chennai-Bangalore (Feb 24 - Mar 8, 2025) |
| **N002** | 2025-01-20 | Ahmedabad-Mumbai | Yes (festival surcharge) | **VALID** for Ahmedabad-Mumbai (week of Jan 20, 2025) |
| **N003** | 2025-05-05 | All Routes | Yes (+5-7% diesel hike) | **VALID** for nationwide 5-7% baseline shifts |
| **N004** | 2024-03-11 | All Routes | Route NOT in dataset | **INVALID** (Guardrail test) |
| **N005** | 2024-07-29 | Mumbai-Delhi | Explicitly "costs not affected" | **INVALID** (Guardrail test) |
| **N006** | 2025-09-22 | All Routes | "Demand stable, no disruptions" | **INVALID** (Guardrail test: does NOT justify cost rise) |
| **N007** | 2024-05-20 | Delhi-Jaipur | Road resurfaced, improved | **INVALID** (No cost rise) |
| **N008** | 2025-06-09 | Kolkata-Bhubaneswar| Normal conditions | **INVALID** (No cost rise) |
| **N009** | 2025-03-17 | Chennai-Bangalore | Flood repairs completed, normalized| **INVALID** (Signals normalization, not hike) |
| **N010** | 2025-10-27 | All Routes | Compliance costs absorbed | **INVALID** (Explicitly absorbed without rate change) |

### 5.2 Deterministic Verification Guardrails
Before any LLM generates an explanation:
1. **Corridor Verification:** Note must match corridor name or be `All Routes`.
2. **Temporal Window Verification:** `week_of` must overlap the note's specified disruption window.
3. **Causal Impact Verification:** Note must explicitly describe a cost-increasing mechanism. Notes explicitly citing "costs not affected", "absorbed", or "normal" are rejected.
4. **Fallback Integrity:** If no note passes the verification filter, `matched_note_id` is forced to empty string `""` and the verdict is forced to `Yes` (unexplained).

---

## 6. System Architecture & Components

```
                   +---------------------------+
                   |   shipment_records.csv    |
                   +-------------+-------------+
                                 |
                                 v
                   +---------------------------+
                   |   Weekly Metric Engine    |  (Weighted cost/t-km,
                   |  (Python Data Pipeline)   |   trailing-8 avg, peer avg)
                   +-------------+-------------+
                                 |
                                 v
                   +---------------------------+
                   |  Anomaly Detector Module  |  (Threshold & trend filter)
                   +-------------+-------------+
                                 |
                                 v
+--------------------+     +---------------------------+
| context_notes.csv  | --> | RAG Note Matching Engine  |  (Vector/semantic +
+--------------------+     | & Grounding Guardrails    |   deterministic temporal)
                           +-------------+-------------+
                                         |
                                         v
                           +---------------------------+
                           | LLM Explanation Generator |  (Temperature=0,
                           | & Token/Cost Measurement  |   Token/cost tracker)
                           +-------------+-------------+
                                         |
                  +----------------------+----------------------+
                  |                                             |
                  v                                             v
     +--------------------------+                 +--------------------------+
     |   output.csv (Contract)  |                 | Interactive Q&A Assistant|
     +--------------------------+                 +--------------------------+
```

### Module Structure:
- `src/core/metrics.py`: Data ingestion, weekly aggregation, baseline computation.
- `src/core/detector.py`: Cost anomaly detection based on history and peer deltas.
- `src/rag/retriever.py`: Note indexing, semantic retrieval, and guardrail verification.
- `src/llm/explainer.py`: Explanation generation, prompt templates, token logging.
- `src/cli/assistant.py`: Interactive CLI for stakeholder queries.
- `tests/test_pipeline.py`: Comprehensive test suite (unit tests, integration tests, guardrail checks).
- `run_pipeline.py`: Main executable reproducing the 3 runs, checking diffs, and outputting token logs.

---

## 7. Execution Plan & Implementation Steps

### Step 1: Ingestion & Exact Metric Computation
- Build pure Python robust engine to aggregate 2,940 shipments into 728 route-weeks.
- Compute trailing 8-week baseline and peer route baseline.
- Unit test to verify exact decimals against `sample_output_format_v2.csv` for Delhi-Jaipur, Ahmedabad-Mumbai, and Mumbai-Pune.

### Step 2: Anomaly Identification
- Implement detector identifying cost spikes exceeding baseline thresholds.
- Verify candidate anomaly set covers all sample benchmarks and operational disruptions.

### Step 3: RAG Retrieval & Verification Engine
- Build embedding/lexical retriever indexing `context_notes.csv`.
- Implement strict rule-based verification filter (corridor match, date window, cost impact).
- Verify negative test cases (N004, N005, N006, N010) are never accepted as justifications.

### Step 4: Explanation Generation & Token Accounting
- Integrate LLM reasoning engine with temperature=0.0.
- Track exact prompt tokens, completion tokens, call counts, and dollar costs.
- Provide deterministic rule-grounded generator as fallback ensuring zero-token and zero-drift operation.

### Step 5: Reproducibility Protocol & 3-Run Verification
- Run full pipeline 3 consecutive times.
- Compare SHA256 hashes and row-by-row diffs across all 3 runs.
- Document zero variance in numbers, flags, and cited notes.

### Step 6: Interactive Q&A Assistant (Stretch Goal)
- Build interactive conversational interface allowing stakeholders to query routes (e.g., "Why did Chennai-Bangalore spike in late Feb 2025?").

### Step 7: Documentation & Deliverables
- Generate `output.csv` matching contract exactly.
- Produce comprehensive `README.md` with methodology, evaluation results, token cost log, and walkthrough guide.
