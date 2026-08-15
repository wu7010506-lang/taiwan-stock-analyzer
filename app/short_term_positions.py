"""Durable, auditable management for ranking-derived short-term positions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from app.database import Database
from app.short_term_trade import (
    COMMISSION_RATE_EACH_SIDE,
    SLIPPAGE_RATE_EACH_SIDE,
    TRANSACTION_TAX_RATE_SELL,
    cost_adjusted_break_even_price,
)


class ShortTermPositionOpen(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    market: str = Field(pattern="^(TWSE|TPEx)$")
    signal_date: date
    strategy_version: str = Field(min_length=1, max_length=100)
    source: Literal["ranking", "individual_analysis"] = "ranking"
    entry_date: date
    entry_price: float = Field(gt=0)
    shares: int = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_trade_levels(self):
        if self.entry_date < self.signal_date:
            raise ValueError("實際買進日不可早於訊號日")
        if self.stop_price >= self.entry_price:
            raise ValueError("停損價必須低於實際買進價")
        if self.target_price <= self.entry_price:
            raise ValueError("目標價必須高於實際買進價")
        return self


class ShortTermPositionExecution(BaseModel):
    action: Literal["reduce", "exit"]
    execution_date: date
    execution_price: float = Field(gt=0)
    shares: int = Field(gt=0)
    reason: str | None = Field(None, max_length=200)


class ManualShortTermPositionOpen(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    entry_date: date
    entry_price: float = Field(gt=0)
    shares: int = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_trade_levels(self):
        if self.stop_price >= self.entry_price:
            raise ValueError("停損價必須低於實際買進價")
        if self.target_price <= self.entry_price:
            raise ValueError("目標價必須高於實際買進價")
        return self


def _position_prices(database: Database, row: dict, as_of_date: date) -> list[dict]:
    with database.connect() as connection:
        prices = connection.execute(
            """SELECT * FROM daily_prices
               WHERE symbol=? AND market=? AND trade_date>=? AND trade_date<=?
               ORDER BY trade_date ASC LIMIT 40""",
            (row["symbol"], row["market"], row["entry_date"], as_of_date.isoformat()),
        ).fetchall()
    return [dict(price) for price in prices]


def evaluate_short_term_position(
    row: dict,
    prices: list[dict],
    market_latest_date: str | None,
) -> dict:
    """Apply the frozen close-to-next-open exit rules to one open position."""
    latest = prices[-1] if prices else None
    latest_date = str(latest.get("trade_date")) if latest else None
    current_close = float(latest["close"]) if latest and latest.get("close") is not None else None
    sessions_held = len(prices)
    base = {
        "holding_sessions": sessions_held,
        "price_date": latest_date,
        "current_close": current_close,
        "execution_timing": "以最新收盤檢查；若觸發，下一交易日開盤執行",
        "research_only": True,
    }
    if current_close is None or not latest_date:
        return {
            **base,
            "action": "data_pending",
            "label": "等待行情資料",
            "reason": "缺少買進後的收盤行情，暫不提出賣出建議。",
            "suggested_shares": 0,
        }
    if market_latest_date and latest_date < market_latest_date:
        return {
            **base,
            "action": "data_pending",
            "label": "個股行情尚未更新",
            "reason": f"個股資料停在 {latest_date}，市場最新資料為 {market_latest_date}。",
            "suggested_shares": 0,
        }

    remaining = int(row["remaining_shares"])
    active_stop = float(row["active_stop"])
    target = float(row["target_price"])
    if current_close <= active_stop:
        return {
            **base,
            "action": "exit_next_open",
            "label": "下一交易日開盤全數賣出",
            "reason": f"收盤 {current_close:g} 已觸及停損 {active_stop:g}。",
            "suggested_shares": remaining,
        }
    if sessions_held >= 10:
        return {
            **base,
            "action": "exit_next_open",
            "label": "下一交易日開盤全數賣出",
            "reason": "已持有 10 個交易日，依短線規則到期出場。",
            "suggested_shares": remaining,
        }
    if not bool(row["target_reduction_executed"]) and current_close >= target:
        suggested = max(1, remaining // 2)
        return {
            **base,
            "action": "reduce_next_open",
            "label": "下一交易日開盤賣出一半",
            "reason": f"收盤 {current_close:g} 已達目標價 {target:g}。",
            "suggested_shares": suggested,
        }
    return {
        **base,
        "action": "hold",
        "label": "續抱並每日檢查",
        "reason": "尚未觸及停損、目標或 10 日到期條件。",
        "suggested_shares": 0,
    }


def open_short_term_position(database: Database, payload: ShortTermPositionOpen) -> dict:
    instrument = database.get_instrument(payload.symbol)
    if not instrument or instrument["market"] != payload.market:
        raise ValueError("找不到這檔股票或市場別不一致")
    with database.connect() as connection:
        existing = connection.execute(
            """SELECT id FROM short_term_positions
               WHERE symbol=? AND market=? AND status='open'""",
            (payload.symbol, payload.market),
        ).fetchone()
        if existing:
            raise ValueError("這檔股票已有進行中的短線持倉")
        cursor = connection.execute(
            """INSERT INTO short_term_positions(
                   symbol, market, signal_date, strategy_version, source, entry_date,
                   entry_price, initial_shares, remaining_shares, original_stop,
                   active_stop, target_price
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.symbol,
                payload.market,
                payload.signal_date.isoformat(),
                payload.strategy_version,
                payload.source,
                payload.entry_date.isoformat(),
                payload.entry_price,
                payload.shares,
                payload.shares,
                payload.stop_price,
                payload.stop_price,
                payload.target_price,
            ),
        )
        position_id = int(cursor.lastrowid)
        connection.execute(
            """INSERT INTO short_term_position_events(
                   position_id, event_type, event_date, execution_price, shares,
                   reason, remaining_shares_after, active_stop_after
               ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?)""",
            (
                position_id,
                payload.entry_date.isoformat(),
                payload.entry_price,
                payload.shares,
                (
                    "ranking_signal_purchase"
                    if payload.source == "ranking"
                    else "individual_analysis_purchase"
                ),
                payload.shares,
                payload.stop_price,
            ),
        )
    return {"id": position_id, "symbol": payload.symbol, "status": "open"}


def open_manual_short_term_position(
    database: Database, payload: ManualShortTermPositionOpen
) -> dict:
    instrument = database.get_instrument(payload.symbol)
    if not instrument:
        raise ValueError("找不到這檔股票；請先更新全市場清單")
    return open_short_term_position(
        database,
        ShortTermPositionOpen(
            symbol=payload.symbol,
            market=instrument["market"],
            signal_date=payload.entry_date,
            strategy_version="manual-individual-analysis-v1",
            source="individual_analysis",
            entry_date=payload.entry_date,
            entry_price=payload.entry_price,
            shares=payload.shares,
            stop_price=payload.stop_price,
            target_price=payload.target_price,
        ),
    )


def _market_latest_dates(database: Database) -> dict[str, str]:
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT market, MAX(trade_date) AS trade_date
               FROM daily_prices WHERE close > 0 GROUP BY market"""
        ).fetchall()
    return {str(row["market"]): str(row["trade_date"]) for row in rows if row["trade_date"]}


def short_term_position_summary(database: Database, as_of_date: date | None = None) -> dict:
    as_of_date = as_of_date or datetime.now(ZoneInfo("Asia/Taipei")).date()
    with database.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                """SELECT p.*, i.name, i.industry
                   FROM short_term_positions p
                   JOIN instruments i ON i.symbol=p.symbol AND i.market=p.market
                   WHERE p.status='open'
                   ORDER BY p.entry_date DESC, p.id DESC"""
            )
        ]
        event_rows = connection.execute(
            """SELECT e.*, p.symbol
               FROM short_term_position_events e
               JOIN short_term_positions p ON p.id=e.position_id
               ORDER BY e.event_date DESC, e.id DESC LIMIT 50"""
        ).fetchall()
    events_by_position: dict[int, list[dict]] = {}
    for event in event_rows:
        events_by_position.setdefault(int(event["position_id"]), []).append(dict(event))

    market_dates = _market_latest_dates(database)
    positions = []
    for row in rows:
        prices = _position_prices(database, row, as_of_date)
        decision = evaluate_short_term_position(row, prices, market_dates.get(row["market"]))
        current_close = decision["current_close"]
        remaining = int(row["remaining_shares"])
        entry_price = float(row["entry_price"])
        row["decision"] = decision
        row["events"] = events_by_position.get(int(row["id"]), [])
        row["market_latest_date"] = market_dates.get(row["market"])
        row["market_value"] = round(current_close * remaining, 2) if current_close else None
        row["unrealized_return_percent"] = (
            round((current_close / entry_price - 1) * 100, 2) if current_close else None
        )
        positions.append(row)
    return {
        "as_of": as_of_date.isoformat(),
        "active_count": len(positions),
        "action_count": sum(
            row["decision"]["action"] in {"reduce_next_open", "exit_next_open"}
            for row in positions
        ),
        "positions": positions,
        "execution_cost_assumptions": {
            "commission_rate_each_side_percent": COMMISSION_RATE_EACH_SIDE * 100,
            "transaction_tax_sell_percent": TRANSACTION_TAX_RATE_SELL * 100,
            "slippage_each_side_percent": SLIPPAGE_RATE_EACH_SIDE * 100,
        },
        "rule": "停損優先；第 10 個交易日全數出場；目標價只賣一半一次，成交後停損提高至成本後損益兩平價。",
        "research_only": True,
    }


def record_short_term_execution(
    database: Database,
    symbol: str,
    payload: ShortTermPositionExecution,
) -> dict:
    with database.connect() as connection:
        raw = connection.execute(
            """SELECT * FROM short_term_positions
               WHERE symbol=? AND status='open' ORDER BY id DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
        if not raw:
            raise ValueError("找不到進行中的短線持倉")
        row = dict(raw)
        remaining = int(row["remaining_shares"])
        if payload.execution_date.isoformat() < row["entry_date"]:
            raise ValueError("成交日不可早於買進日")
        if payload.shares > remaining:
            raise ValueError("成交股數不可超過剩餘股數")
        if payload.action == "exit" and payload.shares != remaining:
            raise ValueError("全數出場時，成交股數必須等於剩餘股數")
        if payload.action == "reduce" and bool(row["target_reduction_executed"]):
            raise ValueError("目標價減碼已執行過，不可重複登記")
        if payload.action == "reduce" and remaining > 1 and payload.shares >= remaining:
            raise ValueError("賣出一半不可等於全部持股；若要全數賣出請選擇全數出場")

        remaining_after = remaining - payload.shares
        active_stop = float(row["active_stop"])
        event_type = "exit"
        status = "closed" if remaining_after == 0 else "open"
        close_reason = payload.reason or "short_term_exit"
        target_reduction_executed = int(row["target_reduction_executed"])
        if payload.action == "reduce":
            event_type = "target_reduce"
            close_reason = payload.reason or "target_price_reached"
            target_reduction_executed = 1
            active_stop = max(
                active_stop,
                cost_adjusted_break_even_price(float(row["entry_price"])),
            )

        connection.execute(
            """UPDATE short_term_positions
               SET remaining_shares=?, active_stop=?, target_reduction_executed=?,
                   status=?, closed_at=?, close_reason=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                remaining_after,
                active_stop,
                target_reduction_executed,
                status,
                payload.execution_date.isoformat() if status == "closed" else None,
                close_reason if status == "closed" else None,
                row["id"],
            ),
        )
        connection.execute(
            """INSERT INTO short_term_position_events(
                   position_id, event_type, event_date, execution_price, shares,
                   reason, remaining_shares_after, active_stop_after
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id"],
                event_type,
                payload.execution_date.isoformat(),
                payload.execution_price,
                payload.shares,
                close_reason,
                remaining_after,
                active_stop,
            ),
        )
    return {
        "symbol": symbol,
        "status": status,
        "remaining_shares": remaining_after,
        "active_stop": active_stop,
        "target_reduction_executed": bool(target_reduction_executed),
    }
