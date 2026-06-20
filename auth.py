"""
auth.py — SatyaX Clerk Authentication Module
Verifies Clerk session JWTs via JWKS and provides Flask route decorators.
"""

import os
import time
import json
import functools
from typing import Optional, Dict, Any

import jwt                         # PyJWT
import requests
from flask import request, redirect, url_for, session, g

# ── Configuration ─────────────────────────────────────────────────────────────

CLERK_SECRET_KEY    = os.getenv("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
CLERK_FRONTEND_API  = os.getenv("CLERK_FRONTEND_API", "")   # e.g. https://xxx.clerk.accounts.dev

# Derive FRONTEND_API from publishable key if not set explicitly
if not CLERK_FRONTEND_API and CLERK_PUBLISHABLE_KEY:
    try:
        import base64
        # pk_test_BASE64$ or pk_live_BASE64$
        b64 = CLERK_PUBLISHABLE_KEY.split("_", 2)[2].rstrip("$")
        # Pad base64
        b64 += "=" * (-len(b64) % 4)
        CLERK_FRONTEND_API = "https://" + base64.b64decode(b64).decode().rstrip("$")
    except Exception:
        pass

CLERK_JWKS_URL      = f"{CLERK_FRONTEND_API}/.well-known/jwks.json" if CLERK_FRONTEND_API else ""
CLERK_API_BASE      = "https://api.clerk.com/v1"

# ── JWKS Cache ────────────────────────────────────────────────────────────────

_jwks_cache: Dict[str, Any] = {}
_jwks_expiry: float = 0
JWKS_TTL = 3600  # 1 hour


def get_jwks() -> Dict:
    """Fetch Clerk's JWKS (public keys), cached for JWKS_TTL seconds."""
    global _jwks_cache, _jwks_expiry
    if _jwks_cache and time.time() < _jwks_expiry:
        return _jwks_cache
    if not CLERK_JWKS_URL:
        return {}
    try:
        resp = requests.get(CLERK_JWKS_URL, timeout=5)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_expiry = time.time() + JWKS_TTL
        return _jwks_cache
    except Exception as e:
        print(f"[auth] JWKS fetch error: {e}")
        return _jwks_cache or {}


def _find_public_key(kid: str):
    """Find and return the RSA public key object for the given key ID."""
    from jwt.algorithms import RSAAlgorithm
    jwks = get_jwks()
    keys = jwks.get("keys", [])
    for key_data in keys:
        if key_data.get("kid") == kid:
            return RSAAlgorithm.from_jwk(json.dumps(key_data))
    return None


# ── Session Verification ──────────────────────────────────────────────────────

def verify_session_token(token: str) -> Optional[Dict]:
    """
    Decode and verify a Clerk session JWT.
    Returns the decoded payload dict, or None if invalid.
    """
    if not token:
        return None
    try:
        # Peek at header to get kid
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            return None

        public_key = _find_public_key(kid)
        if not public_key:
            # Refresh JWKS once and retry
            global _jwks_cache, _jwks_expiry
            _jwks_expiry = 0
            _jwks_cache = {}
            get_jwks()
            public_key = _find_public_key(kid)
            if not public_key:
                return None

        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},   # Clerk doesn't use aud by default
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError as e:
        print(f"[auth] JWT invalid: {e}")
        return None
    except Exception as e:
        print(f"[auth] verify error: {e}")
        return None


def get_session_payload() -> Optional[Dict]:
    """Read and verify the __session cookie from the current Flask request."""
    token = request.cookies.get("__session")
    if not token:
        return None
    return verify_session_token(token)


# ── Clerk Backend API ─────────────────────────────────────────────────────────

def get_clerk_user(user_id: str) -> Optional[Dict]:
    """
    Fetch user details from Clerk Backend API.
    Returns dict with: id, email, first_name, last_name, image_url, created_at, public_metadata
    """
    if not CLERK_SECRET_KEY or not user_id:
        return None
    try:
        resp = requests.get(
            f"{CLERK_API_BASE}/users/{user_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"[auth] Clerk API error: {e}")
        return None


def parse_user(clerk_user: Dict) -> Dict:
    """Extract a clean user dict from the Clerk API response."""
    emails = clerk_user.get("email_addresses", [])
    primary_email_id = clerk_user.get("primary_email_address_id")
    email = ""
    for e in emails:
        if e.get("id") == primary_email_id:
            email = e.get("email_address", "")
            break
    if not email and emails:
        email = emails[0].get("email_address", "")

    metadata = clerk_user.get("public_metadata", {})
    role = metadata.get("role", "user").lower()

    first = clerk_user.get("first_name") or ""
    last  = clerk_user.get("last_name")  or ""
    name  = f"{first} {last}".strip() or email.split("@")[0]

    return {
        "user_id":    clerk_user.get("id", ""),
        "name":       name,
        "first_name": first,
        "email":      email,
        "avatar":     clerk_user.get("image_url", ""),
        "role":       role,
        "is_admin":   role == "admin",
        "created_at": clerk_user.get("created_at", 0),
    }


def get_current_user() -> Optional[Dict]:
    """
    Get the current authenticated user from the request.
    Returns a clean user dict, or None if not authenticated.
    Caches on flask.g for the request lifetime.
    """
    if hasattr(g, "_sx_user"):
        return g._sx_user

    payload = get_session_payload()
    if not payload:
        g._sx_user = None
        return None

    user_id = payload.get("sub")
    if not user_id:
        g._sx_user = None
        return None

    # Build user from JWT payload (fast path — no API call needed for basic info)
    # Full user data fetched from Clerk API for profile/admin pages
    g._sx_user = {
        "user_id": user_id,
        "name":    payload.get("name", ""),
        "email":   payload.get("email", ""),
        "avatar":  "",
        "role":    (payload.get("public_metadata") or {}).get("role", "user"),
        "is_admin": (payload.get("public_metadata") or {}).get("role", "user") == "admin",
    }
    return g._sx_user


def get_current_user_full() -> Optional[Dict]:
    """
    Get current user with full data fetched from Clerk API.
    Use on profile/dashboard pages where avatar and metadata are needed.
    """
    payload = get_session_payload()
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    clerk_data = get_clerk_user(user_id)
    if not clerk_data:
        # Fallback to payload
        return get_current_user()
    return parse_user(clerk_data)


# ── Route Decorators ──────────────────────────────────────────────────────────

def require_auth(f):
    """
    Decorator: redirect to /sign-in if user is not authenticated.
    Passes `current_user` kwarg to the wrapped function.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect("/sign-in")
        return f(*args, current_user=user, **kwargs)
    return decorated


def require_admin(f):
    """
    Decorator: redirect non-admins to /dashboard.
    Requires authentication first (redirects to /sign-in if not logged in).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user_full()
        if not user:
            return redirect("/sign-in")
        if not user.get("is_admin"):
            return redirect("/dashboard?error=access_denied")
        return f(*args, current_user=user, **kwargs)
    return decorated


def optional_auth(f):
    """
    Decorator: passes `current_user` (or None) without redirecting.
    Use on public routes that benefit from knowing if user is logged in.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        return f(*args, current_user=user, **kwargs)
    return decorated


# ── Clerk Admin API helpers ───────────────────────────────────────────────────

def list_clerk_users(limit: int = 50, offset: int = 0) -> list:
    """List users from Clerk (admin use only)."""
    if not CLERK_SECRET_KEY:
        return []
    try:
        resp = requests.get(
            f"{CLERK_API_BASE}/users",
            params={"limit": limit, "offset": offset, "order_by": "-created_at"},
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return [parse_user(u) for u in resp.json()]
        return []
    except Exception as e:
        print(f"[auth] list_users error: {e}")
        return []


def get_clerk_user_count() -> int:
    """Get total user count from Clerk."""
    if not CLERK_SECRET_KEY:
        return 0
    try:
        resp = requests.get(
            f"{CLERK_API_BASE}/users/count",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("total_count", 0)
        return 0
    except Exception:
        return 0


# ── Template context helper ───────────────────────────────────────────────────

def auth_context() -> Dict:
    """
    Returns a dict of auth-related template variables.
    Inject this into render_template calls: **auth_context()
    """
    return {
        "clerk_pk":       CLERK_PUBLISHABLE_KEY,
        "clerk_frontend": CLERK_FRONTEND_API,
        "current_user":   get_current_user(),
        "is_authed":      get_current_user() is not None,
    }
