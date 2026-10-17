# FreightTiger Reproducibility Report Across 3 Untouched Runs

## Checksum Summary
- **Run 1 File:** `output_run1.csv` | **SHA256:** `e8b6b7e98bb7a956d50d5c2e6d6f3f165182cbfc14e880ddf3ae1ace22aabf74`
- **Run 2 File:** `output_run2.csv` | **SHA256:** `e8b6b7e98bb7a956d50d5c2e6d6f3f165182cbfc14e880ddf3ae1ace22aabf74`
- **Run 3 File:** `output_run3.csv` | **SHA256:** `e8b6b7e98bb7a956d50d5c2e6d6f3f165182cbfc14e880ddf3ae1ace22aabf74`

## Pairwise Diff Analysis
- **output_run1.csv vs output_run2.csv:** `0 diffs` (Identical)
- **output_run2.csv vs output_run3.csv:** `0 diffs` (Identical)
- **output_run1.csv vs output_run3.csv:** `0 diffs` (Identical)

## Verdict & Grounding Consistency
- **Identical Numbers:** Cost per tonne-km, vs_own_history, and vs_similar_routes match 100% across all 3 runs.
- **Identical Flags:** Anomaly verdicts ('Yes' vs 'No (justified)') match 100% across all 3 runs.
- **Identical Cited Notes:** Matched note IDs match 100% across all 3 runs.
- **Zero Randomness:** Deterministic evaluation at temperature 0.0 guarantees invariant outputs.

**Final Status:** PASSED - 100% REPRODUCIBLE
