"""
Anomaly detector module for FreightTiger shipping cost tracking.

Identifies route-weeks where shipping costs look out of the ordinary
compared to own 8-week history or peer routes of the same route_type.
"""

from typing import List, Dict, Any, Optional, Tuple


class CostAnomalyDetector:
    def __init__(
        self,
        threshold_own_pct: float = 20.0,
        threshold_peer_pct: float = 20.0,
        require_positive_rise: bool = True
    ):
        """
        :param threshold_own_pct: Minimum percentage rise vs trailing 8-week average to trigger flag.
        :param threshold_peer_pct: Minimum percentage rise vs same-week peer average to trigger flag.
        :param require_positive_rise: If True, requires vs_own_pct > 0 so that absolute price declines
                                      are not flagged purely because peers dropped faster.
        """
        self.threshold_own_pct = threshold_own_pct
        self.threshold_peer_pct = threshold_peer_pct
        self.require_positive_rise = require_positive_rise

    def is_candidate_anomaly(self, record: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Determine whether a single route-week record is an out-of-the-ordinary cost rise.
        """
        vs_own = record.get("vs_own_pct")
        vs_peer = record.get("vs_peer_pct")

        if vs_own is None or vs_peer is None:
            return False, "Insufficient baseline data"

        # Check positive rise requirement
        if self.require_positive_rise and vs_own <= 0.0:
            return False, "Cost is not rising vs own history"

        breached_own = vs_own >= self.threshold_own_pct
        breached_peer = vs_peer >= self.threshold_peer_pct

        if breached_own or breached_peer:
            reasons = []
            if breached_own:
                reasons.append(f"vs_own (+{vs_own:.1f}% >= +{self.threshold_own_pct:.1f}%)")
            if breached_peer:
                reasons.append(f"vs_peer (+{vs_peer:.1f}% >= +{self.threshold_peer_pct:.1f}%)")
            return True, " & ".join(reasons)

        return False, "Within normal thresholds"

    def detect_anomalies(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Scan all route-week records and return only those flagged as candidate anomalies.
        """
        anomalies = []
        for rec in records:
            is_anomaly, reason_trigger = self.is_candidate_anomaly(rec)
            if is_anomaly:
                rec_copy = dict(rec)
                rec_copy["anomaly_trigger"] = reason_trigger
                anomalies.append(rec_copy)
        return anomalies
