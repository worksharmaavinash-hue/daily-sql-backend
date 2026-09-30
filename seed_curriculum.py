import asyncio
import os
import sys

# Allow import from backend/app if needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.seed_curriculum import main

if __name__ == "__main__":
    asyncio.run(main())
