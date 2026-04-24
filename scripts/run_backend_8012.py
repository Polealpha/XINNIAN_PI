import sys
import os
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(ROOT))
RUNTIME_DB = LOCALAPPDATA / "EmoResonance" / "assistant_data" / "auth_runtime_8012.db"

if __name__ == "__main__":
    RUNTIME_DB.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("AUTH_DB_PATH", str(RUNTIME_DB))
    uvicorn.run(app, host="127.0.0.1", port=8012)
