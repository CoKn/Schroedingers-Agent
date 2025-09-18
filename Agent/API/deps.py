# Agent/API/deps.py

import os
from fastapi import Depends, HTTPException, status, WebSocket, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)

async def verify_token(
    creds: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
):
    """Raise 401 unless the client sent `Authorization: Bearer <token>`."""
    correct = os.getenv("API_BEARER_TOKEN")
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != correct:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def auth_ws(websocket: WebSocket, token: str = Query(None)):
    correct = os.getenv("API_BEARER_TOKEN")
    if token != correct:
        await websocket.close(code=1008)     # policy-violation
        raise HTTPException(401)