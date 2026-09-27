from fastapi import APIRouter

from .routes import export, statements, transactions, upload

api_router = APIRouter()

api_router.include_router(upload.router, tags=["upload"])
api_router.include_router(statements.router, tags=["statements"])
api_router.include_router(transactions.router, tags=["transactions"])
api_router.include_router(export.router, tags=["export"])
