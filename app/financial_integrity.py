from __future__ import annotations


BALANCE_FIELDS = ("total_assets", "total_liabilities", "equity")


def assess_financial_integrity(rows: list[dict]) -> list[str]:
    """Detect implausible, consistent balance-sheet unit changes."""
    ordered = sorted(rows, key=lambda row: (row.get("fiscal_year") or 0,
                                            row.get("fiscal_quarter") or 0))
    for previous, current in zip(ordered, ordered[1:]):
        scale_breaks = 0
        for field in BALANCE_FIELDS:
            before, after = previous.get(field), current.get(field)
            if before in (None, 0) or after is None:
                continue
            ratio = abs(float(after) / float(before))
            if ratio >= 100 or ratio <= .01:
                scale_breaks += 1
        if scale_breaks >= 2:
            return ["financial_unit_scale_anomaly"]
    return []
