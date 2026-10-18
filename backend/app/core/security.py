import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response, status

SESSION_COOKIE_NAME = "ds_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days


def generate_login_code() -> str:
    """Generate a random 6-digit numeric login code."""
    return "".join(secrets.choice("0123456789") for _ in range(6))


def generate_session_token() -> str:
    """Generate a random 32-byte urlsafe session token."""
    return secrets.token_urlsafe(32)


def generate_invite_code() -> str:
    """Generate a random 16-byte urlsafe invite code (>= 10 chars)."""
    return secrets.token_urlsafe(16)


def hash_login_code(email: str, code: str, secret_key: str) -> str:
    """Compute HMAC-SHA256(secret_key, email + ':' + code) for login code."""
    normalized_email = email.strip().lower()
    msg = f"{normalized_email}:{code}".encode()
    return hmac.new(secret_key.encode(), msg, hashlib.sha256).hexdigest()


def verify_login_code(email: str, code: str, expected_hash: str, secret_key: str) -> bool:
    """Constant-time verification of login code HMAC."""
    calculated = hash_login_code(email, code, secret_key)
    return hmac.compare_digest(calculated, expected_hash)


def hash_token(token: str) -> str:
    """Compute SHA-256 hex digest of session token."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_invite_code(code: str) -> str:
    """Compute SHA-256 hex digest of invite code."""
    return hashlib.sha256(code.strip().encode()).hexdigest()


def set_session_cookie(response: Response, token: str, secure: bool) -> None:
    """Set the HttpOnly session cookie on the response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response, secure: bool) -> None:
    """Delete the session cookie on the response."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def verify_csrf(request: Request) -> None:
    """Enforce X-DealScour: 1 header on mutating requests, except request-code and verify."""
    if request.method in ("POST", "PATCH", "DELETE", "PUT"):
        path = request.url.path.rstrip("/")
        if path in ("/api/v1/auth/request-code", "/api/v1/auth/verify"):
            return
        if request.headers.get("X-DealScour") != "1":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF check failed: missing or invalid X-DealScour header",
            )
