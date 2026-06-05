"""
Bootstrap-admin seeding for individual-account auth.

There is no open self-signup: every account is created by an admin. That leaves
a chicken-and-egg problem on a fresh database where no admin exists yet. This
module seeds exactly one admin from the environment on startup, and ONLY when
the users collection is empty, so an established deployment is never mutated.

Idempotent: if any user already exists, this is a no-op. Fail-fast: if the DB
is empty but the bootstrap credentials are not configured, startup raises so
the operator notices immediately rather than booting an unreachable UI.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from config import get_settings
from constants import ENV_BOOTSTRAP_ADMIN_EMAIL, ENV_BOOTSTRAP_ADMIN_PASSWORD
from custom_types.db_schemas import UserRole
from db.repositories.users import UsersRepository
from observability.app import get_logger
from rag.auth.passwords import hash_password

logger = get_logger(__name__)


async def ensure_bootstrap_admin(db: AsyncIOMotorDatabase) -> None:
    """Seed the first admin when the users collection is empty.

    No-op when any user already exists. Raises RuntimeError when the database
    is empty but the bootstrap credentials are missing, since a UI with no
    accounts and no way to create one is unusable.

    Args:
        db: Live Motor database handle.
    """
    try:
        repo = UsersRepository(db)
        existing = await repo.count_users()
        if existing > 0:
            logger.info(
                "Bootstrap admin skipped: users already exist",
                extra={"event": "bootstrap_admin_skipped", "function": "ensure_bootstrap_admin", "user_count": existing},
            )
            return

        settings = get_settings()
        email = settings.login.bootstrap_admin_email
        password = settings.login.bootstrap_admin_password
        if not email or not password:
            raise RuntimeError(
                f"The users collection is empty but bootstrap admin credentials are not "
                f"configured. Set {ENV_BOOTSTRAP_ADMIN_EMAIL} and "
                f"{ENV_BOOTSTRAP_ADMIN_PASSWORD} so the first admin account can be created."
            )

        user_id = await repo.create_user(
            email=email,
            communities=[],
            role=UserRole.ADMIN,
            password_hash=hash_password(password),
        )
        logger.info(
            "Bootstrap admin created",
            extra={"event": "bootstrap_admin_created", "function": "ensure_bootstrap_admin", "user_id": user_id, "email": email},
        )
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(
            "Failed to ensure bootstrap admin",
            extra={"event": "bootstrap_admin_failed", "function": "ensure_bootstrap_admin", "error": str(e)},
        )
        raise
