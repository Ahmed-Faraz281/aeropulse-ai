from typing import Union
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.core.security import create_access_token, verify_password
from backend.app.models.user import User, UserRole
from backend.app.schemas.user import LoginRequest, Token, UserResponse

router = APIRouter()


@router.post("/login", response_model=Token, summary="User Authentication & Token Issuance")
async def login(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Authenticate with username/email and password. Returns JWT bearer token and user metadata.
    Supports both application/json body and OAuth2 form data for OpenAPI compatibility.
    """
    username = ""
    password = ""

    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")
    else:
        try:
            body = await request.json()
            username = body.get("username", "")
            password = body.get("password", "")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request body format",
            )

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both username and password are required",
        )

    # Locate user by username or email
    user = (
        db.query(User)
        .filter((User.username == username) | (User.email == username))
        .first()
    )

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account. Contact an administrator.",
        )

    access_token = create_access_token(subject=user.username)

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse, summary="Get Current Authenticated User")
def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the currently authenticated user's safe profile.
    Password and password_hash are strictly omitted.
    """
    return UserResponse.model_validate(current_user)


@router.post("/logout", summary="User Logout")
def logout(current_user: User = Depends(get_current_user)):
    """
    Logs out the authenticated user. In a stateless JWT architecture,
    client discards the token.
    """
    return {
        "message": f"Successfully logged out user {current_user.username}",
        "status": "success",
    }


@router.get(
    "/admin-only",
    summary="Admin Authorization Verification",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def test_admin_access(current_user: User = Depends(get_current_user)):
    """Sample protected endpoint restricted exclusively to users with ADMIN role."""
    return {
        "message": f"Welcome Admin {current_user.username}",
        "role": current_user.role,
    }


@router.get(
    "/analyst-or-admin",
    summary="Analyst or Admin Authorization Verification",
    dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.ANALYST))],
)
def test_analyst_access(current_user: User = Depends(get_current_user)):
    """Sample protected endpoint accessible to ADMIN and ANALYST roles."""
    return {
        "message": f"Authorized analytical access for {current_user.username}",
        "role": current_user.role,
    }
