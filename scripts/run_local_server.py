from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"C:\codex_runtime\taiwan_stock_packages")
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
