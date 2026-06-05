"""
Admin-only user management router (individual-account auth).

Create (invite), list, password-reset, disable/enable, and delete user
accounts. There is no open self-signup: every account is created by an admin.
Every route requires an ADMIN session via the router-level require_admin
dependency.

A password reset bumps the target user's session epoch, which revokes their
live sessions. An admin cannot disable or delete their own account, so the last
admin cannot accidentally lock the whole org out.
"""

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from constants import (
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_CONFLICT,
    HTTP_STATUS_NOT_FOUND,
    ROUTE_AUTH_USER_BY_ID,
    ROUTE_AUTH_USER_DISABLE,
    ROUTE_AUTH_USER_PASSWORD,
    ROUTE_AUTH_USERS,
)
from custom_types.api_schemas import (
    AdminUserView,
    CreateUserRequest,
    CurrentUser,
    ResetPasswordRequest,
    SetDisabledRequest,
)
from custom_types.db_schemas import UserRole
from custom_types.field_keys import UserKeys
from api.auth import require_admin
from db.connection import get_database
from db.repositories.users import UsersRepository
from observability.app import get_logger
from rag.auth.passwords import hash_password

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["admin-users"], dependencies=[Depends(require_admin)])

_DUPLICATE_EMAIL_MESSAGE = "A user with that email already exists"
_USER_NOT_FOUND_MESSAGE = "User not found"
_SELF_MUTATION_MESSAGE = "Admins cannot disable or delete their own account"


def _to_admin_view(user: dict) -> AdminUserView:
    """Project a raw user document to the admin view (no password_hash)."""
    return AdminUserView(
        user_id=user[UserKeys.USER_ID],
        email=user[UserKeys.EMAIL],
        role=UserRole(user[UserKeys.ROLE]),
        communities=list(user.get(UserKeys.COMMUNITIES, [])),
        disabled=bool(user.get(UserKeys.DISABLED, False)),
    )


@router.post(ROUTE_AUTH_USERS, response_model=AdminUserView)
async def create_user(request: CreateUserRequest, _: CurrentUser = Depends(require_admin)) -> AdminUserView:
    """Create (invite) a new user account with a hashed initial password."""
    email = str(request.email)
    try:
        repo = UsersRepository(await get_database())
        try:
            user_id = await repo.create_user(
                email=email,
                communities=list(request.communities),
                role=request.role,
                password_hash=hash_password(request.password),
            )
        except DuplicateKeyError:
            logger.warning(
                "Admin create_user rejected: duplicate email",
                extra={"event": "admin_create_duplicate", "function": "create_user", "email": email},
            )
            raise HTTPException(status_code=HTTP_STATUS_CONFLICT, detail=_DUPLICATE_EMAIL_MESSAGE)

        created = await repo.find_by_user_id(user_id)
        logger.info(
            "Admin created user",
            extra={"event": "admin_create_user", "function": "create_user", "user_id": user_id, "role": str(request.role)},
        )
        return _to_admin_view(created)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "create_user failed",
            extra={"event": "admin_create_error", "function": "create_user", "email": email, "error": str(e)},
        )
        raise


@router.get(ROUTE_AUTH_USERS, response_model=list[AdminUserView])
async def list_users(_: CurrentUser = Depends(require_admin)) -> list[AdminUserView]:
    """List all users (password_hash stripped via the AdminUserView projection)."""
    try:
        repo = UsersRepository(await get_database())
        users = await repo.list_users()
        return [_to_admin_view(u) for u in users]
    except Exception as e:
        logger.error(
            "list_users failed",
            extra={"event": "admin_list_error", "function": "list_users", "error": str(e)},
        )
        raise


@router.post(ROUTE_AUTH_USER_PASSWORD, response_model=AdminUserView)
async def reset_password(user_id: str, request: ResetPasswordRequest, _: CurrentUser = Depends(require_admin)) -> AdminUserView:
    """Set a new password for a user (revokes their live sessions)."""
    try:
        repo = UsersRepository(await get_database())
        existing = await repo.find_by_user_id(user_id)
        if existing is None:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_USER_NOT_FOUND_MESSAGE)

        await repo.set_password(user_id, hash_password(request.password))
        logger.info(
            "Admin reset user password",
            extra={"event": "admin_reset_password", "function": "reset_password", "user_id": user_id},
        )
        return _to_admin_view(await repo.find_by_user_id(user_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "reset_password failed",
            extra={"event": "admin_reset_error", "function": "reset_password", "user_id": user_id, "error": str(e)},
        )
        raise


@router.post(ROUTE_AUTH_USER_DISABLE, response_model=AdminUserView)
async def set_disabled(user_id: str, request: SetDisabledRequest, current: CurrentUser = Depends(require_admin)) -> AdminUserView:
    """Enable or disable a user account. Admins cannot disable themselves."""
    try:
        if request.disabled and user_id == current.user_id:
            raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail=_SELF_MUTATION_MESSAGE)

        repo = UsersRepository(await get_database())
        existing = await repo.find_by_user_id(user_id)
        if existing is None:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_USER_NOT_FOUND_MESSAGE)

        await repo.set_disabled(user_id, request.disabled)
        logger.info(
            "Admin set user disabled flag",
            extra={"event": "admin_set_disabled", "function": "set_disabled", "user_id": user_id, "disabled": request.disabled},
        )
        return _to_admin_view(await repo.find_by_user_id(user_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "set_disabled failed",
            extra={"event": "admin_disable_error", "function": "set_disabled", "user_id": user_id, "error": str(e)},
        )
        raise


@router.delete(ROUTE_AUTH_USER_BY_ID, response_model=AdminUserView)
async def delete_user(user_id: str, current: CurrentUser = Depends(require_admin)) -> AdminUserView:
    """Delete a user account. Admins cannot delete themselves."""
    try:
        if user_id == current.user_id:
            raise HTTPException(status_code=HTTP_STATUS_BAD_REQUEST, detail=_SELF_MUTATION_MESSAGE)

        repo = UsersRepository(await get_database())
        existing = await repo.find_by_user_id(user_id)
        if existing is None:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_USER_NOT_FOUND_MESSAGE)

        view = _to_admin_view(existing)
        await repo.delete_user(user_id)
        logger.info(
            "Admin deleted user",
            extra={"event": "admin_delete_user", "function": "delete_user", "user_id": user_id},
        )
        return view
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "delete_user failed",
            extra={"event": "admin_delete_error", "function": "delete_user", "user_id": user_id, "error": str(e)},
        )
        raise
