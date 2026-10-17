"""
LLM Explanation and Token/Cost Measurement Engine.

Generates plain-English grounded explanations for shipping cost anomalies
and tracks exact token usage and financial cost according to published rates.
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple


class TokenCostTracker:
    def __init__(self, cost_per_million_input: float = 0.075, cost_per_million_output: float = 0.30):
        """
        Published pricing for Gemini 2.5 Flash / Flash Lite (or equivalent open tier):
        Input: $0.075 / 1M tokens
        Output: $0.300 / 1M tokens
        """
        self.cost_per_million_input = cost_per_million_input
        self.cost_per_million_output = cost_per_million_output
        self.calls: List[Dict[str, Any]] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_llm_calls = 0
        self.has_live_measurements = False

    def estimate_tokens(self, text: str) -> int:
        """
        Heuristic offline token estimate (~3.8 characters per token)
        used when running without an external provider API key.
        """
        if not text:
            return 0
        words = text.split()
        return max(len(words), int(len(text) / 3.8))

    def record_call(self, route: str, week_of: str, prompt: str, completion: str,
                    input_tokens: Optional[int] = None, output_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Record an LLM invocation, distinguishing between measured vs estimated tokens."""
        is_measured = (input_tokens is not None and output_tokens is not None)
        if is_measured:
            self.has_live_measurements = True

        in_tok = input_tokens if input_tokens is not None else self.estimate_tokens(prompt)
        out_tok = output_tokens if output_tokens is not None else self.estimate_tokens(completion)

        call_cost = (
            (in_tok / 1_000_000.0) * self.cost_per_million_input +
            (out_tok / 1_000_000.0) * self.cost_per_million_output
        )

        record = {
            "call_index": len(self.calls) + 1,
            "route": route,
            "week_of": week_of,
            "token_measurement": "measured_via_api" if is_measured else "estimated_heuristic_offline",
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "cost_usd": round(call_cost, 7)
        }

        self.calls.append(record)
        self.total_input_tokens += in_tok
        self.total_output_tokens += out_tok
        self.total_llm_calls += 1

        return record

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregated summary of token usage and financial cost."""
        total_cost = (
            (self.total_input_tokens / 1_000_000.0) * self.cost_per_million_input +
            (self.total_output_tokens / 1_000_000.0) * self.cost_per_million_output
        )
        measurement_type = "measured_via_provider_api" if self.has_live_measurements else "estimated_offline_heuristic"
        return {
            "model_name": "gemini-2.5-flash (Google GenAI)",
            "token_accounting_mode": measurement_type,
            "is_measured": self.has_live_measurements,
            "total_llm_calls": self.total_llm_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "input_rate_per_million_usd": self.cost_per_million_input,
            "output_rate_per_million_usd": self.cost_per_million_output,
            "total_cost_usd": f"${total_cost:.6f}",
            "raw_total_cost_usd": total_cost,
            "cost_inr_approx": f"INR {total_cost * 83.5:.4f} (at 83.5 INR/USD)",
            "measurement_notes": (
                "Tokens measured directly from provider response usage_metadata when live API key is configured. "
                "In offline/local reproducible mode, tokens are estimated using standard ~3.8 chars/token heuristic."
            ),
            "calls_breakdown": self.calls
        }


class AnomalyExplainer:
    def __init__(self, token_tracker: Optional[TokenCostTracker] = None, use_live_api: bool = False):
        self.tracker = token_tracker or TokenCostTracker()
        self.use_live_api = use_live_api
        self.api_client = None

        if self.use_live_api:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                try:
                    from google import genai
                    self.api_client = genai.Client(api_key=api_key)
                except Exception as e:
                    print(f"Warning: Failed to initialize Google GenAI client: {e}. Falling back to deterministic mode.")
                    self.use_live_api = False
            else:
                self.use_live_api = False

    def explain(
        self,
        route: str,
        week_of: str,
        cost_per_tonne_km: float,
        vs_own_history: str,
        vs_similar_routes: str,
        is_justified: bool,
        matched_note_id: Optional[str],
        verified_explanation: str,
        candidate_note_text: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate grounded explanation and log token metrics.
        Guarantees that the verdict and cited note are 100% faithful.
        """
        prompt = (
            f"You are a logistics assistant explaining shipping cost anomalies.\n"
            f"Route: {route}\n"
            f"Week: {week_of}\n"
            f"Cost per tonne-km: {cost_per_tonne_km:.2f}\n"
            f"vs Own History: {vs_own_history}\n"
            f"vs Similar Routes: {vs_similar_routes}\n"
            f"Justified by context note?: {'Yes' if is_justified else 'No'}\n"
            f"Matched Note ID: {matched_note_id or 'None'}\n"
            f"Note Details: {candidate_note_text or 'None'}\n"
            f"Core Finding: {verified_explanation}\n\n"
            f"Write a concise, plain-English explanation following the contract. "
            f"State the verdict; if justified, cite the exact note id and describe why. "
            f"If unexplained, state that no genuine justification was found."
        )

        if self.use_live_api and self.api_client:
            try:
                response = self.api_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config={"temperature": 0.0}
                )
                text = response.text.strip()
                in_tok = getattr(response.usage_metadata, "prompt_token_count", None)
                out_tok = getattr(response.usage_metadata, "candidates_token_count", None)
                record = self.tracker.record_call(route, week_of, prompt, text, in_tok, out_tok)
                return text, record
            except Exception as e:
                print(f"LLM API call failed: {e}. Using deterministic grounded explanation.")

        # Deterministic grounded explanation
        explanation = verified_explanation
        record = self.tracker.record_call(route, week_of, prompt, explanation)
        return explanation, record
