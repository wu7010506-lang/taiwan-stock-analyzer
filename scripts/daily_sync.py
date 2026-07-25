from app.config import settings
from app.daily_sync import run_daily_close_sync
from app.database import Database


if __name__ == "__main__":
    result = run_daily_close_sync(Database(settings.database_path))
    print(result)
    raise SystemExit(0 if result["status"] in {"completed", "partial"} else 1)
