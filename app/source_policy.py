from __future__ import annotations


def data_source_catalog() -> list[dict]:
    """Document source priority and safe degradation for each dataset."""
    return [
        {"dataset": "instruments", "label": "上市櫃公司清單", "primary": "TWSE／TPEx 官方 OpenAPI", "fallback": "最近成功的本機快取", "fallback_kind": "cache", "formal_use": "公司存在性可沿用；需顯示更新時間"},
        {"dataset": "prices", "label": "日價量", "primary": "TWSE／TPEx 官方行情 API", "fallback": "最近成功的本機快取", "fallback_kind": "cache", "formal_use": "超過 7 日即不得產生正式 vNext 建議"},
        {"dataset": "revenues", "label": "月營收", "primary": "MOPS 官方月營收", "fallback": "最近成功的本機快取", "fallback_kind": "cache", "formal_use": "超過 62 日即不得產生正式 vNext 建議"},
        {"dataset": "valuations", "label": "估值", "primary": "TWSE／TPEx 官方估值資料", "fallback": "最近成功的本機快取", "fallback_kind": "cache", "formal_use": "超過 14 日即不得產生正式 vNext 建議"},
        {"dataset": "financials", "label": "財報與現金流", "primary": "MOPS 官方財報", "fallback": "FinMind 轉載 MOPS／最近成功快取", "fallback_kind": "secondary_then_cache", "formal_use": "保留來源；超過 190 日即不得正式推薦"},
        {"dataset": "institutions", "label": "法人買賣", "primary": "TWSE／TPEx 官方三大法人資料", "fallback": "最近成功的本機快取", "fallback_kind": "cache", "formal_use": "超過 7 日即不得產生正式 vNext 建議"},
        {"dataset": "ownership", "label": "股權分散", "primary": "TDCC 股權分散表", "fallback": "最近成功的本機快取", "fallback_kind": "cache", "formal_use": "僅作籌碼背景，不以缺漏補中性分"},
    ]
