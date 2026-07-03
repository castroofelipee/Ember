from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env
from ember.db import get_db
from ember.schemas.auth import LoginRequest, LoginResponse, SignupRequest, SignupResponse
from ember.services.auth import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    login,
    logout,
    refresh,
    signup,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

REFRESH_TOKEN_COOKIE = "refresh_token"
# Scoped to /api/auth (not just /api/auth/refresh): per RFC 6265, a cookie's Path
# must be a prefix of the request path, so /api/auth/logout would never receive
# a cookie scoped to /api/auth/refresh alone.
REFRESH_TOKEN_COOKIE_PATH = "/api/auth"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path=REFRESH_TOKEN_COOKIE_PATH,
        max_age=env["REFRESH_TOKEN_TTL_DAYS"] * 24 * 60 * 60,
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def register(data: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    try:
        user = await signup(db, data)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    return SignupResponse.model_validate(user)


@router.post("/login", status_code=status.HTTP_200_OK)
async def login_route(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    try:
        access_token, refresh_token = await login(
            db,
            data,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from exc

    _set_refresh_cookie(response, refresh_token)
    return LoginResponse(access_token=access_token)


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def refresh_route(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    raw_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    try:
        access_token, new_refresh_token = await refresh(db, raw_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        ) from exc

    _set_refresh_cookie(response, new_refresh_token)
    return LoginResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_route(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    raw_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    await logout(db, raw_token)
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path=REFRESH_TOKEN_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )
