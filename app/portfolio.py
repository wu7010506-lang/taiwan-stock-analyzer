from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field, model_validator

from app.database import Database


class PositionUpdate(BaseModel):
    average_cost: float | None = Field(None, gt=0)
    shares: int | None = Field(None, ge=0)
    purchase_date: str | None = None
    stop_loss: float | None = Field(None, gt=0)
    target_price: float | None = Field(None, gt=0)
    investment_horizon: str | None = Field(None, pattern="^(short|long)$")
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_position(self):
        if (self.shares or 0) > 0 and self.average_cost is None:
            raise ValueError("持有股數大於零時必須填寫平均成本")
        if self.stop_loss and self.target_price and self.stop_loss >= self.target_price:
            raise ValueError("停損價必須低於目標價")
        return self


def portfolio_summary(database: Database) -> dict:
    rows = database.list_watchlist()
    held = [row for row in rows if row["is_held"] and row["market_value"] is not None]
    total_cost = sum(row["cost_basis"] for row in held)
    total_value = sum(row["market_value"] for row in held)
    profit = total_value - total_cost
    industries: dict[str, float] = defaultdict(float)
    for row in held:
        industries[row["industry"] or "未分類"] += row["market_value"]
    exposure = sorted(({"industry": industry, "market_value": value,
                        "weight_percent": value / total_value * 100 if total_value else 0}
                       for industry, value in industries.items()),
                      key=lambda item: item["market_value"], reverse=True)
    warnings = []
    for row in held:
        weight = row["market_value"] / total_value * 100 if total_value else 0
        row["portfolio_weight_percent"] = weight
        if weight > 35:
            warnings.append(f"{row['symbol']} {row['name']} 占投資組合 {weight:.1f}%，集中度偏高")
        if row["stop_triggered"]:
            warnings.append(f"{row['symbol']} {row['name']} 已跌破設定停損價")
        if row["target_reached"]:
            warnings.append(f"{row['symbol']} {row['name']} 已達設定目標價")
    for item in exposure:
        if item["weight_percent"] > 50:
            warnings.append(f"產業 {item['industry']} 占 {item['weight_percent']:.1f}%，產業集中度偏高")
    return {"watching_count": len(rows), "held_count": len(held),
            "total_cost": total_cost, "total_market_value": total_value,
            "unrealized_profit": profit,
            "unrealized_return_percent": profit / total_cost * 100 if total_cost else None,
            "largest_position_percent": max((row["portfolio_weight_percent"] for row in held),
                                             default=0),
            "industry_exposure": exposure, "warnings": warnings, "positions": held}
