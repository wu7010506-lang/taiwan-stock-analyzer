from __future__ import annotations


INDUSTRY_NAMES = {
    "03": "塑化", "10": "鋼鐵", "14": "營建", "15": "航運",
    "17": "金融", "23": "油電燃氣", "24": "半導體", "26": "光電",
}


def industry_category(code: str | None) -> str:
    value = str(code or "").zfill(2)
    if value == "17":
        return "financial"
    if value == "24":
        return "semiconductor"
    if value in {"03", "08", "10", "14", "15", "23", "26"}:
        return "cyclical"
    return "general"


def industry_label(code: str | None) -> str:
    category = industry_category(code)
    return {"financial": "金融專用模型", "semiconductor": "半導體資本密集模型",
            "cyclical": "景氣循環模型", "general": "一般企業模型"}[category]
