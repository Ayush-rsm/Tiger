"""
Main Pipeline Runner for FreightTiger Smart Shipping Cost Assistant.

Executes:
1. Data Ingestion & Metric Aggregation
2. Anomaly Detection vs Own History & Similar Routes
3. RAG Retrieval & Guardrail Note Verification
4. Plain-English Grounded Explanation & Token/Cost Measurement
5. Output CSV Generation matching contract
6. 3-Run Reproducibility Verification
"""

import os
import sys
import csv
import json
import hashlib
import argparse
from typing import List, Dict, Any, Tuple

from src.core.metrics import ShipmentMetricsEngine
from src.core.detector import CostAnomalyDetector
from src.rag.retriever import NotesRAGRetriever
from src.llm.explainer import AnomalyExplainer, TokenCostTracker
from src.cli.assistant import CostQueryAssistant


OUTPUT_COLUMNS = [
    "route",
    "week_of",
    "cost_per_tonne_km",
    "vs_own_history",
    "vs_similar_routes",
    "flagged",
    "matched_note_id",
    "reason"
]


def execute_pipeline(
    shipment_path: str = "shipment_records.csv",
    notes_path: str = "context_notes.csv",
    threshold_own: float = 20.0,
    threshold_peer: float = 20.0,
    use_live_api: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], NotesRAGRetriever]:
    """
    Run one complete pass of the pipeline.
    Returns:
        output_rows: List of final anomaly output dictionaries matching CSV contract.
        all_metrics: Full weekly metrics for all 728 route-weeks.
        cost_summary: Detailed token and financial cost accounting.
        retriever: The active RAG retriever instance.
    """
    # 1. Ingestion & Metrics
    metrics_engine = ShipmentMetricsEngine(shipment_path)
    all_metrics = metrics_engine.compute_all_metrics()

    # 2. Anomaly Detection
    detector = CostAnomalyDetector(
        threshold_own_pct=threshold_own,
        threshold_peer_pct=threshold_peer,
        require_positive_rise=True
    )
    candidate_anomalies = detector.detect_anomalies(all_metrics)

    # 3. RAG Retrieval & Verification
    retriever = NotesRAGRetriever(notes_path)

    # 4. Explanation & Token Tracking
    tracker = TokenCostTracker()
    explainer = AnomalyExplainer(token_tracker=tracker, use_live_api=use_live_api)

    output_rows = []
    # Sort candidate anomalies chronologically, then by route
    candidate_anomalies.sort(key=lambda x: (x["week_of"], x["route"]))

    for anom in candidate_anomalies:
        route = anom["route"]
        week_of = anom["week_of"]
        cost = anom["cost_per_tonne_km"]
        vs_own = anom["vs_own_history"]
        vs_peer = anom["vs_similar_routes"]

        # Verify against context notes
        is_justified, note_id, note_obj, verified_finding = retriever.verify_justification(route, week_of)

        flag_verdict = "No (justified)" if is_justified else "Yes"
        matched_id = note_id if is_justified else ""

        # Generate explanation & track token usage
        note_text = note_obj.note_text if note_obj else None
        reason_prose, _ = explainer.explain(
            route=route,
            week_of=week_of,
            cost_per_tonne_km=cost,
            vs_own_history=vs_own,
            vs_similar_routes=vs_peer,
            is_justified=is_justified,
            matched_note_id=matched_id,
            verified_explanation=verified_finding,
            candidate_note_text=note_text
        )

        row = {
            "route": route,
            "week_of": week_of,
            "cost_per_tonne_km": f"{cost:.2f}",
            "vs_own_history": vs_own,
            "vs_similar_routes": vs_peer,
            "flagged": flag_verdict,
            "matched_note_id": matched_id,
            "reason": reason_prose
        }
        output_rows.append(row)

    cost_summary = tracker.get_summary()
    return output_rows, all_metrics, cost_summary, retriever


def write_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """
    Write rows to CSV strictly adhering to required column headers and format.
    Uses atomic replace with retry backoff to guard against transient Windows file locks.
    """
    import time
    temp_path = filepath + ".tmp"
    with open(temp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            os.replace(temp_path, filepath)
            return
        except (PermissionError, OSError):
            time.sleep(0.1)

    # Final attempt fallback
    if os.path.exists(temp_path):
        os.replace(temp_path, filepath)


def compute_sha256(filepath: str) -> str:
    """Compute SHA256 checksum of file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="FreightTiger Shipping Cost Assistant Pipeline")
    parser.add_argument("--shipments", default="shipment_records.csv", help="Path to shipment records CSV")
    parser.add_argument("--notes", default="context_notes.csv", help="Path to context notes CSV")
    parser.add_argument("--output", default="output.csv", help="Path to output CSV")
    parser.add_argument("--reproduce", action="store_true", help="Run 3 consecutive executions and verify reproducibility")
    parser.add_argument("--query", type=str, default=None, help="Ask the assistant a plain-English question")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive Q&A assistant session")
    args = parser.parse_args()

    print("=================================================================")
    print("      FREIGHTTIGER SMART SHIPPING COST ASSISTANT PIPELINE       ")
    print("=================================================================\n")

    # Run primary execution
    print("[1/3] Executing core intelligence pipeline...")
    output_rows, all_metrics, cost_summary, retriever = execute_pipeline(
        shipment_path=args.shipments,
        notes_path=args.notes
    )

    write_csv(output_rows, args.output)
    print(f"      Successfully generated '{args.output}' with {len(output_rows)} flagged candidate anomalies.")

    # Also save full metrics CSV for auditing
    full_metrics_path = "full_weekly_metrics.csv"
    temp_full_metrics = full_metrics_path + ".tmp"
    with open(temp_full_metrics, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "route", "week_of", "route_type", "cost_per_tonne_km",
            "vs_own_history", "vs_similar_routes", "shipment_count",
            "total_freight_cost", "total_tonne_km"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_metrics)

    for attempt in range(10):
        try:
            os.replace(temp_full_metrics, full_metrics_path)
            break
        except (PermissionError, OSError):
            import time
            time.sleep(0.1)

    print(f"      Saved comprehensive weekly metrics (728 route-weeks) to '{full_metrics_path}'.\n")

    # Save token cost summary
    with open("tokencost_summary.json", "w", encoding="utf-8") as f:
        json.dump(cost_summary, f, indent=2)

    print("[2/3] Token and Financial Cost Accounting (Full Run):")
    print(f"      Total LLM Invocations: {cost_summary['total_llm_calls']}")
    print(f"      Total Input Tokens:    {cost_summary['total_input_tokens']}")
    print(f"      Total Output Tokens:   {cost_summary['total_output_tokens']}")
    print(f"      Total Tokens:          {cost_summary['total_tokens']}")
    print(f"      Estimated Cost (USD):  {cost_summary['total_cost_usd']}")
    print("      Saved detailed cost log to 'tokencost_summary.json'.\n")

    # 3-Run Reproducibility Check
    if args.reproduce:
        print("[3/3] Running Reproducibility Verification Across 3 Untouched Runs...")
        run_files = ["output_run1.csv", "output_run2.csv", "output_run3.csv"]
        hashes = []

        for i, rfile in enumerate(run_files, start=1):
            rows, _, _, _ = execute_pipeline(args.shipments, args.notes)
            write_csv(rows, rfile)
            sha = compute_sha256(rfile)
            hashes.append(sha)
            print(f"      Run {i}: wrote {len(rows)} rows to '{rfile}' -> SHA256: {sha[:16]}...")

        # Assert all hashes are identical
        if len(set(hashes)) == 1:
            print("\n      SUCCESS: 100% Bitwise Reproducibility Confirmed! (0 diff across all 3 runs)")
        else:
            print("\n      WARNING: Outputs differed across runs!")
            sys.exit(1)

    # Q&A / Interactive Assistant
    assistant = CostQueryAssistant(output_rows, all_metrics, retriever.notes)

    if args.query:
        print(f"\n[Q&A] User Query: \"{args.query}\"")
        ans = assistant.answer_query(args.query)
        print(f"[Q&A] Assistant:\n{ans}\n")

    if args.interactive:
        print("\n--- Interactive Assistant Mode (type 'exit' to quit) ---")
        while True:
            try:
                user_q = input("\nAsk Assistant: ")
                if not user_q or user_q.lower() in ("exit", "quit", "q"):
                    break
                print("\n" + assistant.answer_query(user_q))
            except (KeyboardInterrupt, EOFError):
                break


if __name__ == "__main__":
    main()
