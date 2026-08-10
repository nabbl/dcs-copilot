"""HTTP account endpoints; realtime media continues to use WebSocket."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from .auth import (
    AccountAlreadyExists,
    AuthenticatedPrincipal,
    AuthenticationError,
    AuthService,
    TokenPair,
)


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=256)
    device_id: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=256)
    device_id: str = Field(min_length=1, max_length=128)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class AccountResponse(TokenResponse):
    user_id: str


def auth_router(auth: AuthService) -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["authentication"])

    @router.post(
        "/register",
        response_model=AccountResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def register(request: CredentialsRequest) -> AccountResponse:
        try:
            user_id, pair = await auth.register(
                request.email, request.password, request.device_id
            )
        except AccountAlreadyExists as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except AuthenticationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return account_response(user_id, pair)

    @router.post("/token", response_model=AccountResponse)
    async def token(request: CredentialsRequest) -> AccountResponse:
        try:
            user_id, pair = await auth.login(
                request.email, request.password, request.device_id
            )
        except AuthenticationError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return account_response(user_id, pair)

    @router.post("/refresh", response_model=TokenResponse)
    async def refresh(request: RefreshRequest) -> TokenResponse:
        try:
            pair = await auth.refresh(request.refresh_token, request.device_id)
        except AuthenticationError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return token_response(pair)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: LogoutRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        principal = bearer_principal(auth, authorization)
        assert principal.user_id is not None
        try:
            await auth.revoke_refresh(request.refresh_token, principal.user_id)
        except AuthenticationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    @router.get("/me")
    async def me(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        principal = bearer_principal(auth, authorization)
        assert principal.user_id is not None
        return {"user_id": principal.user_id, "device_id": principal.device_id}

    return router


def bearer_principal(
    auth: AuthService, authorization: str | None
) -> AuthenticatedPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        principal = auth.verify_access_token(authorization.removeprefix("Bearer "))
    except AuthenticationError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if principal.user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "development tokens cannot access account endpoints",
        )
    return principal


def token_response(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


def account_response(user_id: str, pair: TokenPair) -> AccountResponse:
    return AccountResponse(user_id=user_id, **token_response(pair).model_dump())
