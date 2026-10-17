"""
Metrics computation engine for FreightTiger shipment records.

Implements exact weekly aggregations, trailing 8-week history rolling averages,
and peer route averages per route_type bucket according to the case study brief.
"""

import csv
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional


def parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD date string."""
    return datetime.strptime(date_str.strip(), "%Y-%m-%d")


def get_week_of(date_str: str) -> str:
    """
    Get the Monday date (YYYY-MM-DD) for the given shipment date string.
    Weeks run Monday to Sunday.
    """
    dt = parse_date(date_str)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


class ShipmentMetricsEngine:
    def __init__(self, shipment_file_path: str):
        self.shipment_file_path = shipment_file_path
        self.shipments: List[Dict[str, Any]] = []
        self.routes: List[str] = []
        self.route_types: Dict[str, str] = {}
        self.all_weeks: List[str] = []
        
        # Raw aggregations: (route, week_of) -> dict of sums
        self.weekly_sums: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
            lambda: {"freight_cost": 0.0, "tonne_km": 0.0, "shipment_count": 0}
        )
        
        # Final unit cost per tonne-km: (route, week_of) -> float
        self.route_week_cost: Dict[Tuple[str, str], float] = {}
        
        # Full computed metrics: List of record dictionaries
        self.computed_records: List[Dict[str, Any]] = []

    def load_data(self) -> None:
        """Load shipment records and perform schema validation."""
        with open(self.shipment_file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_cols = {
                "shipment_id", "origin", "destination", "route_type",
                "material", "quantity_tonnes", "distance_km",
                "freight_cost_inr", "shipment_date", "transporter"
            }
            if not required_cols.issubset(set(reader.fieldnames or [])):
                missing = required_cols - set(reader.fieldnames or [])
                raise ValueError(f"Missing required columns in shipment records: {missing}")

            for row in reader:
                origin = row["origin"].strip()
                dest = row["destination"].strip()
                route = f"{origin}-{dest}"
                rtype = row["route_type"].strip()
                qty = float(row["quantity_tonnes"])
                dist = float(row["distance_km"])
                cost = float(row["freight_cost_inr"])
                date_str = row["shipment_date"].strip()
                week_of = get_week_of(date_str)

                self.shipments.append(row)
                self.route_types[route] = rtype
                
                # Aggregate totals
                self.weekly_sums[(route, week_of)]["freight_cost"] += cost
                self.weekly_sums[(route, week_of)]["tonne_km"] += (qty * dist)
                self.weekly_sums[(route, week_of)]["shipment_count"] += 1

        self.routes = sorted(list(self.route_types.keys()))
        weeks_set = set(w for (_, w) in self.weekly_sums.keys())
        self.all_weeks = sorted(list(weeks_set))

    def compute_unit_costs(self) -> None:
        """
        Compute cost_per_tonne_km = total freight cost / (quantity x distance)
        for every active route-week.
        """
        for (route, week_of), sums in self.weekly_sums.items():
            t_km = sums["tonne_km"]
            if t_km > 0:
                self.route_week_cost[(route, week_of)] = sums["freight_cost"] / t_km
            else:
                self.route_week_cost[(route, week_of)] = 0.0

    def compute_all_metrics(self) -> List[Dict[str, Any]]:
        """
        Compute weekly costs and exact comparison baselines:
        1. vs. own history: trailing 8-week rolling average strictly before current week.
           If fewer than 8 prior weeks exist, average all available prior weeks without padding.
        2. vs. similar routes: same-week average across all OTHER routes sharing the same route_type.
        """
        self.load_data()
        self.compute_unit_costs()
        
        self.computed_records = []

        for week_idx, week_of in enumerate(self.all_weeks):
            for route in self.routes:
                if (route, week_of) not in self.route_week_cost:
                    continue

                curr_cost = self.route_week_cost[(route, week_of)]
                rtype = self.route_types[route]

                # 1. Trailing 8-week rolling average of route's own history
                # Takes up to the last 8 weekly observations strictly before the current week
                route_prior_weeks = [
                    pw for pw in self.all_weeks[:week_idx]
                    if (route, pw) in self.route_week_cost
                ]
                prior_costs = [
                    self.route_week_cost[(route, pw)]
                    for pw in route_prior_weeks[-8:]
                ]
                
                if prior_costs:
                    avg_prior = sum(prior_costs) / len(prior_costs)
                    if avg_prior > 0:
                        vs_own_pct = ((curr_cost - avg_prior) / avg_prior) * 100.0
                        own_hist_str = f"{vs_own_pct:+.1f}% vs this route's past average"
                    else:
                        vs_own_pct = None
                        own_hist_str = "N/A (zero baseline)"
                else:
                    avg_prior = None
                    vs_own_pct = None
                    own_hist_str = "N/A (first week)"

                # 2. Similar routes average in the same week (exclude route itself)
                peer_routes = [r for r in self.routes if self.route_types[r] == rtype and r != route]
                peer_costs = [
                    self.route_week_cost[(pr, week_of)]
                    for pr in peer_routes
                    if (pr, week_of) in self.route_week_cost
                ]

                if peer_costs:
                    peer_avg = sum(peer_costs) / len(peer_costs)
                    if peer_avg > 0:
                        vs_peer_pct = ((curr_cost - peer_avg) / peer_avg) * 100.0
                        similar_routes_str = f"{vs_peer_pct:+.1f}% vs similar-length routes this week"
                    else:
                        vs_peer_pct = None
                        similar_routes_str = "N/A (zero baseline)"
                else:
                    peer_avg = None
                    vs_peer_pct = None
                    similar_routes_str = "N/A (no peers)"

                record = {
                    "route": route,
                    "week_of": week_of,
                    "route_type": rtype,
                    "cost_per_tonne_km": round(curr_cost, 2),
                    "raw_cost_per_tonne_km": curr_cost,
                    "avg_prior_8": avg_prior,
                    "vs_own_pct": vs_own_pct,
                    "vs_own_history": own_hist_str,
                    "peer_avg": peer_avg,
                    "vs_peer_pct": vs_peer_pct,
                    "vs_similar_routes": similar_routes_str,
                    "shipment_count": self.weekly_sums[(route, week_of)]["shipment_count"],
                    "total_freight_cost": self.weekly_sums[(route, week_of)]["freight_cost"],
                    "total_tonne_km": self.weekly_sums[(route, week_of)]["tonne_km"]
                }
                self.computed_records.append(record)

        return self.computed_records
