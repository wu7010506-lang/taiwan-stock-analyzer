from __future__ import annotations

from statistics import mean

from app.database import Database
from app.strategy_backtest import strategy_walk_forward_backtest
from app.technical_strategy_backtest import breakout_atr_backtest


FACTOR_ABLATION_CONFIGURATIONS = (
    {"name": "baseline", "weights": {"business_quality": 30, "cashflow_quality": 20,
     "durability": 15, "value": 15, "risk_resilience": 10, "growth_quality": 5, "market_fit": 5}},
    {"name": "cashflow_tilt", "weights": {"business_quality": 25, "cashflow_quality": 30,
     "durability": 10, "value": 15, "risk_resilience": 10, "growth_quality": 5, "market_fit": 5}},
    {"name": "value_safety", "weights": {"business_quality": 30, "cashflow_quality": 20,
     "durability": 15, "value": 25, "risk_resilience": 5, "growth_quality": 0, "market_fit": 5}},
)


def _realized_equity_drawdown(simulation: dict) -> float | None:
    """Drawdown from the trade-account curve; open positions remain at cost."""
    curve = simulation.get("equity_curve") or []
    if not curve:
        return None
    peak, drawdown = float(simulation.get("initial_capital") or curve[0]["equity"]), 0.0
    for row in curve:
        equity = float(row["equity"])
        peak = max(peak, equity)
        if peak:
            drawdown = min(drawdown, equity / peak - 1)
    return round(drawdown * 100, 4)


def technical_execution_assumptions() -> dict:
    """Public contract for every isolated technical strategy experiment."""
    return {
        "version": "technical-execution-contract-v1",
        "scope": "TWSE／TPEx daily OHLCV and stored TAIEX closes only",
        "formal_recommendation_allowed": False,
        "assumptions": [
            {"topic": "訊號與成交", "detail": "訊號只使用當日收盤前可得的 OHLCV；最早在下一交易日開盤成交。"},
            {"topic": "成本", "detail": "預設單邊手續費 14.25 bps、賣出交易稅 30 bps、單邊滑價 5 bps；每個策略結果均保存其參數。"},
            {"topic": "流動性與部位", "detail": "預設次日開盤價×成交量至少 1,000 萬元；總曝險 80%、單股 10%、產業 25%。"},
            {"topic": "日內處理", "detail": "日 OHLC 無法重建盤中順序；同日停損與停利皆可能時，保守地先視為停損。"},
            {"topic": "同曝險基準", "detail": "對每筆已接受交易使用相同進出日、資金限制與成本，配對 TAIEX 收盤價代理；非可成交 ETF 基準。"},
            {"topic": "資料限制", "detail": "尚未完整處理下市、公司行動、除權息、停牌、盤中委託簿與資料修訂；缺漏指數日期時基準直接判定不足。"},
        ],
        "non_claims": [
            "歷史回測、樣本外或紙上結果不構成獲利保證。",
            "未達樣本外、同曝險基準與紙上追蹤門檻的規則不得改變今日決策或正式推薦。",
        ],
    }


def technical_research_governance(database: Database | None = None) -> dict:
    """Publish the fixed technical-research contract used by this site."""
    evidence_matrix = [
        {"strategy": "價量突破＋ATR", "pit_costs_limits": "completed", "oos_matched_benchmark": "completed_proxy", "walk_forward_purge": "pending", "paper_forward": "started", "live_decision": "blocked"},
        {"strategy": "EMA20／100＋ADX＋ATR", "pit_costs_limits": "completed", "oos_matched_benchmark": "completed_proxy", "walk_forward_purge": "pending", "paper_forward": "pending", "live_decision": "blocked"},
        {"strategy": "布林20＋RSI14 均值回歸", "pit_costs_limits": "completed", "oos_matched_benchmark": "completed_proxy", "walk_forward_purge": "pending", "paper_forward": "pending", "live_decision": "blocked"},
    ]
    if database:
        runs = database.list_strategy_experiment_runs("technical_breakout_walk_forward", 1)
        if runs:
            evidence_matrix[0]["walk_forward_purge"] = runs[0]["status"]
    return {
        "version": "technical-research-governance-v1",
        "source": "股票技術分析規則生成、驗證與實作研究報告（2026-08-01）",
        "formal_recommendation_allowed": False,
        "rules": [
            {"name": "價量突破＋ATR", "status": "已實作・研究中", "market_regime": "趨勢／波動擴張", "entry": "20 日突破、量能確認、均線趨勢；訊號後下一交易日開盤", "exit": "ATR 停損、2R 目標或時間出場", "risk": "流動性、成本、滑價、產業與總曝險上限", "decision_use": "僅離線回測與參數穩健性研究"},
            {"name": "vNext 技術時機層", "status": "已實作・輔助", "market_regime": "基本面合格股票的進場／追價風險", "entry": "趨勢、相對強弱、量能與波動確認；不改變品質／估值排名", "exit": "不以單一技術訊號自動賣出持股", "risk": "NATR、MFI、過度乖離與 K 線風險縮減新增部位", "decision_use": "今日決策的等待／縮部位輔助；尚非獨立獲利引擎"},
            {"name": "EMA20／100＋ADX＋ATR", "status": "已實作・研究中", "market_regime": "趨勢", "entry": "EMA20 上穿 EMA100、收盤高於 EMA200、ADX>20、+DI>-DI；下一開盤", "exit": "EMA20 跌回 EMA100、跌破 EMA50 或 ATR 移動停損", "risk": "初始 2.5 ATR、最高收盤−3 ATR、成本與曝險限制", "decision_use": "獨立研究回測；尚未接入今日決策"},
            {"name": "布林20＋RSI14 均值回歸", "status": "已實作・研究中", "market_regime": "短期超賣；未宣稱適用所有市場狀態", "entry": "收盤跌破布林下軌且 RSI<30；下一交易日開盤", "exit": "回到中軌、2 ATR 停損或 10 日時間出場", "risk": "流動性、成本、滑價、產業與總曝險上限", "decision_use": "獨立研究回測；尚未接入今日決策"},
            {"name": "回檔、區間與其他均值回歸", "status": "未實作・候選規格", "market_regime": "必須先定義趨勢或區間狀態", "entry": "規則、資料與交易時點尚未封存", "exit": "尚未封存", "risk": "不得加入今日決策或正式推薦", "decision_use": "需先完成預先宣告、PIT 回測與樣本外驗證"},
        ],
        "required_controls": [
            "訊號僅用形成當時可得資料，收盤訊號最早下一可成交時點執行。",
            "報告手續費、交易稅、滑價、流動性與保守的日內停損／停利順序。",
            "固定候選規則與參數；比較參數鄰域，不以樣本內最高報酬選策略。",
            "使用 walk-forward、封存樣本外區段，以及持有期重疊的 purge／embargo。",
            "揭露倖存者、下市、公司行動、資料修訂與多重測試偏誤。",
            "資料異常、價格缺漏或資格不足時不產生進場決策。",
        ],
        "promotion_requirements": [
            "成本後同曝險超額報酬與最大回撤在樣本外均有足夠樣本支持。",
            "參數鄰域結果穩定，且完整保存測試次數與失敗結果。",
            "紙上投資組合累積足夠前瞻觀測，並完成滑價與交易可行性稽核。",
        ],
        "evidence_matrix": evidence_matrix,
    }


def factor_ablation_study(database: Database, out_of_sample_start: str = "2026-01-01") -> dict:
    """Compare a fixed, documented set of research weights without optimisation."""
    results = []
    for configuration in FACTOR_ABLATION_CONFIGURATIONS:
        report = strategy_walk_forward_backtest(
            database, out_of_sample_start=out_of_sample_start,
            research_weights=configuration["weights"],
        )
        matched = report.get("allocation_matched_benchmark") or {}
        oos_matched = report.get("out_of_sample_allocation_matched_benchmark") or {}
        results.append({"name": configuration["name"], "weights": configuration["weights"],
                        "periods": report.get("periods"),
                        "total_return_percent": report.get("total_return_percent"),
                        "allocation_matched_excess_return_percent": matched.get("excess_return_percent"),
                        "out_of_sample_periods": (report.get("out_of_sample") or {}).get("periods"),
                        "out_of_sample_allocation_matched_excess_return_percent": oos_matched.get("excess_return_percent"),
                        "max_drawdown_percent": report.get("max_drawdown_percent")})
    return {"mode": "isolated_factor_ablation", "research_type": "predeclared_factor_weights",
            "isolated": True, "formal_recommendation_allowed": False,
            "ai_decisioning_enabled": False, "out_of_sample_start": out_of_sample_start,
            "results": results,
            "limitations": ["Configurations are fixed research candidates, not an optimiser or a recommendation change.",
                            "The short historical sample is insufficient to select a production weight set.",
                            "Any candidate must be retested on a locked future sample before it can be considered."]}


def technical_parameter_study(database: Database, out_of_sample_start: str = "2026-01-01") -> dict:
    """Run a bounded, research-only robustness study.

    This is deliberately not an optimizer: configurations are predeclared and
    results cannot alter recommendations, positions, or production parameters.
    """
    configurations = (
        {"name": "baseline", "volume_multiple": 1.5, "min_breakout_percent": 3},
        {"name": "lower_breakout", "volume_multiple": 1.5, "min_breakout_percent": 1},
        {"name": "higher_volume", "volume_multiple": 2.0, "min_breakout_percent": 3},
    )
    results, audit_records = [], []
    for configuration in configurations:
        report = breakout_atr_backtest(database, out_of_sample_start=out_of_sample_start,
                                       **{key: value for key, value in configuration.items() if key != "name"})
        oos = report.get("out_of_sample") or {}
        oos_benchmark = report.get("out_of_sample_allocation_matched_benchmark") or {}
        audit_records.extend(report.get("audit_records", []))
        results.append({"name": configuration["name"], "parameters": report["parameters"],
                        "trades": report["trades"], "win_rate_percent": report["win_rate_percent"],
                        "average_net_return_percent": report["average_net_return_percent"],
                        "out_of_sample_trades": oos.get("trades"),
                        "out_of_sample_excess_return_percent": oos_benchmark.get("excess_return_percent"),
                        "out_of_sample_benchmark_status": oos_benchmark.get("status"),
                        "out_of_sample_realized_equity_drawdown_percent": _realized_equity_drawdown(
                            oos.get("portfolio_simulation") or {}),
                        "diagnostics": report["diagnostics"]})
    return {"mode": "isolated_research_lab", "research_type": "technical_parameter_study",
            "isolated": True, "formal_recommendation_allowed": False,
            "ai_decisioning_enabled": False, "results": results,
            "audit_records": audit_records,
            "out_of_sample_start": out_of_sample_start,
            "test_family": {"family_id": "breakout-neighbourhood-v1", "predeclared_configurations": len(configurations),
                            "selection_prohibited": True,
                            "disclosure": "Three neighbouring configurations are displayed together; the highest historical return is not selected or promoted. Any later promotion requires a separate locked sample, multiple-testing review and paper evidence."},
            "drawdown_disclosure": "Drawdown uses the shared cash account and holds open trades at cost; it is not an intraday or fully marked-to-market maximum drawdown.",
            "limitations": ["This bounded study is not parameter optimization and does not select a winning configuration.",
                            "Results are historical research only; they cannot change formal recommendations or positions.",
                            "AI models remain disabled until point-in-time coverage and conventional benchmark validation are sufficient."]}


def breakout_walk_forward_study(database: Database, *, folds: int = 3, fold_sessions: int = 120,
                                embargo_sessions: int = 5, purge_sessions: int = 20,
                                max_holding_days: int = 20) -> dict:
    """Evaluate the frozen breakout rule on disjoint chronological forward folds.

    There is no model fitting between folds.  The purge/embargo exists to keep
    holdings and observation windows from bleeding between reported periods.
    """
    with database.connect() as connection:
        dates = [row["trade_date"] for row in connection.execute(
            "SELECT trade_date FROM market_index_snapshots ORDER BY trade_date")]
    required = folds * fold_sessions + (folds - 1) * embargo_sessions
    if fold_sessions <= purge_sessions or len(dates) < required:
        return {"mode": "technical_breakout_walk_forward", "formal_recommendation_allowed": False,
                "folds": [], "limitation": "Insufficient index sessions for the predeclared fold geometry."}
    cursor = len(dates)
    windows = []
    for _ in range(folds):
        end, start = cursor - 1, cursor - fold_sessions
        windows.append((dates[start + purge_sessions], dates[end]))
        cursor = start - embargo_sessions
    results, reports = [], []
    for start, end in reversed(windows):
        report = breakout_atr_backtest(database, start_date=start, end_date=end,
                                       out_of_sample_start=start, max_holding_days=max_holding_days)
        reports.append(report)
        matched = report.get("out_of_sample_allocation_matched_benchmark") or {}
        results.append({"start_date": start, "end_date": end, "trades": report["trades"],
                        "oos_trades": (report.get("out_of_sample") or {}).get("trades"),
                        "oos_excess_return_percent": matched.get("excess_return_percent"),
                        "benchmark_status": matched.get("status"),
                        "purge_sessions": purge_sessions, "embargo_sessions_after_fold": embargo_sessions,
                        "parameters": report["parameters"]})
    fold_excess = [row["oos_excess_return_percent"] for row in results]
    audit_records = [record for report in reports for record in report.get("audit_records", [])]
    return {"mode": "technical_breakout_walk_forward", "strategy": "20d_breakout_volume_atr",
            "formal_recommendation_allowed": False, "parameter_refit_allowed": False,
            "folds": results, "purge_sessions": purge_sessions, "embargo_sessions": embargo_sessions,
            "max_holding_days": max_holding_days,
            "out_of_sample": {"periods": len(results), "trades": sum(row["oos_trades"] or 0 for row in results)},
            "out_of_sample_allocation_matched_benchmark": {"status": "fold_level_proxy",
                "excess_return_percent": round(mean(fold_excess), 4) if all(value is not None for value in fold_excess) else None,
                "aggregation": "unweighted_mean_fold_excess_not_compounded"},
            "audit_records": audit_records,
            "limitations": ["Parameters are frozen; folds are evaluation partitions, not an optimiser.",
                            "Each fold forces exits by its end date; the reported purge and embargo prevent overlap between adjacent reported windows.",
                            "Same-exposure TAIEX remains a close-to-close proxy and paper evidence is still required."]}
