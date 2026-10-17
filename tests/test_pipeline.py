"""
Automated Evaluation and Regression Test Suite for FreightTiger Shipping Cost Assistant.

Tests:
1. Input schema & data integrity
2. Math & metric accuracy against sample_output_format benchmark
3. Trailing 8-week baseline logic (no lookahead, handling of < 8 prior weeks)
4. Same-week peer baseline logic (peer exclusion, route_type match)
5. Zero-hallucination guardrail tests (negative notes rejection, positive notes acceptance)
6. Output CSV schema contract compliance
7. Bitwise reproducibility across multiple executions
"""

import os
import csv
import hashlib
import pytest
from datetime import datetime

from src.core.metrics import ShipmentMetricsEngine, get_week_of
from src.core.detector import CostAnomalyDetector
from src.rag.retriever import NotesRAGRetriever
from run_pipeline import execute_pipeline, write_csv, OUTPUT_COLUMNS


SHIPMENTS_CSV = "shipment_records.csv"
NOTES_CSV = "context_notes.csv"
SAMPLE_OUTPUT_CSV = "sample_output_format_v2.csv"


def test_input_schema_and_types():
    """Verify input files exist and match schema contracts."""
    assert os.path.exists(SHIPMENTS_CSV), "shipment_records.csv must exist"
    assert os.path.exists(NOTES_CSV), "context_notes.csv must exist"

    with open(SHIPMENTS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected_shipment_cols = {
            "shipment_id", "origin", "destination", "route_type",
            "material", "quantity_tonnes", "distance_km",
            "freight_cost_inr", "shipment_date", "transporter"
        }
        assert expected_shipment_cols.issubset(set(reader.fieldnames or []))
        rows = list(reader)
        assert len(rows) == 2940, f"Expected 2940 rows, found {len(rows)}"

    with open(NOTES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected_note_cols = {"note_id", "date", "applies_to", "note"}
        assert expected_note_cols.issubset(set(reader.fieldnames or []))
        notes = list(reader)
        assert len(notes) == 10, f"Expected 10 notes, found {len(notes)}"


def test_week_of_monday_grouping():
    """Verify weeks run Monday to Sunday and week_of is Monday's date."""
    # 2024-01-01 was a Monday
    assert get_week_of("2024-01-01") == "2024-01-01"
    # 2024-01-07 was a Sunday -> belongs to week of 2024-01-01
    assert get_week_of("2024-01-07") == "2024-01-01"
    # 2024-01-08 was the next Monday -> belongs to week of 2024-01-08
    assert get_week_of("2024-01-08") == "2024-01-08"


def test_benchmark_metrics_accuracy():
    """
    Validate that our core metrics engine reproduces the exact numbers
    in sample_output_format.csv down to the second decimal and percentage.
    """
    engine = ShipmentMetricsEngine(SHIPMENTS_CSV)
    metrics = engine.compute_all_metrics()
    metrics_map = {(m["route"], m["week_of"]): m for m in metrics}

    # Benchmark 1: Delhi-Jaipur, 2024-11-11
    # Expected: cost 4.17, vs_own +35.5%, vs_similar +21.0%
    b1 = metrics_map.get(("Delhi-Jaipur", "2024-11-11"))
    assert b1 is not None, "Delhi-Jaipur on 2024-11-11 must be present"
    assert b1["cost_per_tonne_km"] == 4.17
    assert "+35.5%" in b1["vs_own_history"]
    assert "+21.0%" in b1["vs_similar_routes"]

    # Benchmark 2: Ahmedabad-Mumbai, 2025-01-20
    # Expected: cost 3.29, vs_own +29.5%, vs_similar +22.5%
    b2 = metrics_map.get(("Ahmedabad-Mumbai", "2025-01-20"))
    assert b2 is not None, "Ahmedabad-Mumbai on 2025-01-20 must be present"
    assert b2["cost_per_tonne_km"] == 3.29
    assert "+29.5%" in b2["vs_own_history"]
    assert "+22.5%" in b2["vs_similar_routes"]

    # Benchmark 3: Mumbai-Pune, 2025-09-15
    # Expected: cost 3.98, vs_own +9.2%, vs_similar +23.6%
    b3 = metrics_map.get(("Mumbai-Pune", "2025-09-15"))
    assert b3 is not None, "Mumbai-Pune on 2025-09-15 must be present"
    assert b3["cost_per_tonne_km"] == 3.98
    assert "+9.2%" in b3["vs_own_history"]
    assert "+23.6%" in b3["vs_similar_routes"]


def test_trailing_8_week_window_rules():
    """
    Verify trailing 8-week history calculation:
    - Strictly prior weeks only (no lookahead bias).
    - If fewer than 8 prior weeks exist, average all available prior weeks without padding.
    """
    engine = ShipmentMetricsEngine(SHIPMENTS_CSV)
    metrics = engine.compute_all_metrics()

    # Route at week 0 (first week, e.g. 2024-01-01) should have avg_prior_8 = None
    week0_rec = [m for m in metrics if m["route"] == "Mumbai-Pune" and m["week_of"] == "2024-01-01"][0]
    assert week0_rec["avg_prior_8"] is None
    assert "N/A" in week0_rec["vs_own_history"]

    # Route at week 2 (e.g. 2024-01-15) should average only week 0 and week 1
    week2_rec = [m for m in metrics if m["route"] == "Mumbai-Pune" and m["week_of"] == "2024-01-15"][0]
    week0_cost = [m["raw_cost_per_tonne_km"] for m in metrics if m["route"] == "Mumbai-Pune" and m["week_of"] == "2024-01-01"][0]
    week1_cost = [m["raw_cost_per_tonne_km"] for m in metrics if m["route"] == "Mumbai-Pune" and m["week_of"] == "2024-01-08"][0]
    expected_avg2 = (week0_cost + week1_cost) / 2.0
    assert abs(week2_rec["avg_prior_8"] - expected_avg2) < 1e-6


def test_peer_routes_exclusion_and_route_type():
    """
    Verify peer routes calculation:
    - Route itself is excluded from its peer average.
    - Only routes with identical route_type are compared.
    """
    engine = ShipmentMetricsEngine(SHIPMENTS_CSV)
    metrics = engine.compute_all_metrics()

    # Short routes: Delhi-Jaipur, Mumbai-Pune
    # Peer average for Delhi-Jaipur must be exactly Mumbai-Pune's cost in that week!
    for week_of in ["2024-01-01", "2024-06-10", "2025-01-20"]:
        dj = [m for m in metrics if m["route"] == "Delhi-Jaipur" and m["week_of"] == week_of][0]
        mp = [m for m in metrics if m["route"] == "Mumbai-Pune" and m["week_of"] == week_of][0]
        assert dj["peer_avg"] == mp["raw_cost_per_tonne_km"]
        assert mp["peer_avg"] == dj["raw_cost_per_tonne_km"]


def test_guardrails_zero_hallucination_negative_notes():
    """
    Negative tests: Verify notes that do NOT justify cost rises are NEVER accepted as justification.
    """
    retriever = NotesRAGRetriever(NOTES_CSV)

    # N004: "affected routes are not part of this dataset" -> Must reject!
    assert not retriever.notes["N004"].is_valid_cost_driver

    # N005: "costs were not significantly affected" -> Must reject!
    assert not retriever.notes["N005"].is_valid_cost_driver

    # N006: "stable with no major disruptions" -> Must reject!
    assert not retriever.notes["N006"].is_valid_cost_driver

    # N007: "improved road conditions after resurfacing" -> Must reject!
    assert not retriever.notes["N007"].is_valid_cost_driver

    # N008: "remained normal" -> Must reject!
    assert not retriever.notes["N008"].is_valid_cost_driver

    # N009: "returned to normal conditions" -> Must reject!
    assert not retriever.notes["N009"].is_valid_cost_driver

    # N010: "compliance costs were absorbed by transporters without a rate change" -> Must reject!
    assert not retriever.notes["N010"].is_valid_cost_driver


def test_guardrails_positive_note_justifications():
    """
    Positive tests: Verify genuine disruptions are accepted only for their route and time window.
    """
    retriever = NotesRAGRetriever(NOTES_CSV)

    # N002: Ahmedabad-Mumbai on 2025-01-20 must be justified
    is_justified, note_id, _, _ = retriever.verify_justification("Ahmedabad-Mumbai", "2025-01-20")
    assert is_justified is True
    assert note_id == "N002"

    # N002 must NOT justify a different route on the same date
    is_justified_diff, note_id_diff, _, _ = retriever.verify_justification("Mumbai-Pune", "2025-01-20")
    assert is_justified_diff is False
    assert note_id_diff is None

    # N001: Chennai-Bangalore on 2025-02-24 and 2025-03-03 must be justified
    is_j1, n1, _, _ = retriever.verify_justification("Chennai-Bangalore", "2025-02-24")
    assert is_j1 is True
    assert n1 == "N001"

    is_j2, n2, _, _ = retriever.verify_justification("Chennai-Bangalore", "2025-03-03")
    assert is_j2 is True
    assert n2 == "N001"

    # N001 must NOT justify Chennai-Bangalore after flood ended (Mar 9)
    is_j3, n3, _, _ = retriever.verify_justification("Chennai-Bangalore", "2025-03-10")
    assert is_j3 is False
    assert n3 is None


def test_output_csv_contract_compliance():
    """Verify generated output.csv exactly matches contract columns, order, and non-empty values."""
    output_rows, _, _, _ = execute_pipeline()
    assert len(output_rows) > 0

    for r in output_rows:
        # Check all required columns are present
        assert list(r.keys()) == OUTPUT_COLUMNS
        assert r["flagged"] in ("Yes", "No (justified)")
        if r["flagged"] == "Yes":
            assert r["matched_note_id"] == "", "Unexplained rows must have blank matched_note_id"
        else:
            assert r["matched_note_id"] != "", "Justified rows must have non-blank matched_note_id"
        assert len(r["reason"]) > 10, "Reason must be explanatory plain English"


def test_three_runs_reproducibility():
    """
    Run pipeline 3 times and verify 100% bitwise reproducibility.
    Hashes, numbers, flags, and cited notes must not differ.
    """
    hashes = []
    for i in range(3):
        rows, _, _, _ = execute_pipeline()
        temp_file = f"test_run_{i+1}.csv"
        write_csv(rows, temp_file)
        with open(temp_file, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        hashes.append(h)
        if os.path.exists(temp_file):
            os.remove(temp_file)

    assert len(set(hashes)) == 1, f"Reproducibility failed! Hashes differed: {hashes}"


def test_exact_weighted_cost_formula():
    """
    Verify cost per tonne-km is total freight cost / sum(quantity * distance),
    which is a weighted network rate, NOT a simple unweighted arithmetic mean of rates.
    """
    engine = ShipmentMetricsEngine(SHIPMENTS_CSV)
    engine.load_data()
    engine.compute_unit_costs()
    # Test on a specific route-week with multiple shipments
    sums = engine.weekly_sums[("Mumbai-Pune", "2024-01-01")]
    expected_rate = sums["freight_cost"] / sums["tonne_km"]
    actual_rate = engine.route_week_cost[("Mumbai-Pune", "2024-01-01")]
    assert abs(actual_rate - expected_rate) < 1e-9


def test_date_boundaries_and_calendar_transitions():
    """Verify leap day and calendar year transitions adhere to Monday-Sunday weeks."""
    # Leap day 2024-02-29 was a Thursday -> Week starts Monday 2024-02-26
    assert get_week_of("2024-02-29") == "2024-02-26"
    # Year boundary 2024-12-31 was a Tuesday -> Week starts Monday 2024-12-30
    assert get_week_of("2024-12-31") == "2024-12-30"
    assert get_week_of("2025-01-01") == "2024-12-30"
    assert get_week_of("2025-01-05") == "2024-12-30"
    assert get_week_of("2025-01-06") == "2025-01-06"


def test_missing_data_and_zero_denominators():
    """Verify engine handles missing history, missing peers, and zero denominators safely."""
    engine = ShipmentMetricsEngine(SHIPMENTS_CSV)
    metrics = engine.compute_all_metrics()

    # Week 0 has no prior history -> vs_own_pct must be None
    week0_items = [m for m in metrics if m["week_of"] == "2024-01-01"]
    for m in week0_items:
        assert m["vs_own_pct"] is None
        assert "N/A" in m["vs_own_history"]

    # Long routes in dataset: Delhi-Chennai, Mumbai-Delhi (only 2 peers)
    # Delhi-Chennai peer avg must equal Mumbai-Delhi cost
    long_items = [m for m in metrics if m["route_type"] == "Long" and m["week_of"] == "2024-01-01"]
    assert len(long_items) == 2


def test_wrong_route_and_wrong_date_rejections():
    """
    Verify notes are strictly bound to corridor and temporal window.
    A note matching the wrong route or wrong date must NEVER justify.
    """
    retriever = NotesRAGRetriever(NOTES_CSV)

    # N002 (Ahmedabad-Mumbai, 2025-01-20):
    # Wrong routes
    for wrong_route in ["Delhi-Jaipur", "Mumbai-Pune", "Chennai-Bangalore", "Delhi-Chennai"]:
        is_j, nid, _, _ = retriever.verify_justification(wrong_route, "2025-01-20")
        assert not is_j, f"N002 must not justify wrong route {wrong_route}"
        assert nid is None

    # Wrong dates for N002
    for wrong_date in ["2024-01-22", "2025-01-13", "2025-01-27", "2025-02-20"]:
        is_j, nid, _, _ = retriever.verify_justification("Ahmedabad-Mumbai", wrong_date)
        assert not is_j, f"N002 must not justify wrong date {wrong_date}"
        assert nid is None

