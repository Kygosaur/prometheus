import os
import sys
from pathlib import Path

import uvicorn


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    uvicorn.run(
        "planning_agent.api:app",
        host="127.0.0.1",
        port=int(os.getenv("PLANNING_WEB_PORT", "8010")),
        reload=os.getenv("PLANNING_WEB_RELOAD", "false").casefold() == "true",
    )
