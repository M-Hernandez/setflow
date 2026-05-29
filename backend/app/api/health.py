from fastapi import APIRouter

from app.db import check_db

router = APIRouter()


@router.get("/health")
async def health():
    try:
        await check_db()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "degraded", "database": str(e)}
