"""Central role-based authorization policy for state-changing requests."""

from fnmatch import fnmatch


ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_INSPECTOR = "inspector"
ROLE_TECHNICIAN = "technician"
ROLE_VIEWER = "viewer"

ADMIN_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN})
MANAGER_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_MANAGER})
INSPECTOR_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_MANAGER, ROLE_INSPECTOR})
TECHNICIAN_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_MANAGER, ROLE_TECHNICIAN})

# Exact endpoint-path policy. A path that is not listed here falls back to
# MANAGER_ROLES for writes. This makes newly added write endpoints fail closed
# for inspector/technician/viewer until their permissions are intentionally
# reviewed and added to this matrix.
PATH_ROLE_RULES = (
    # User administration is strictly administrative.
    ("/api/users", ADMIN_ROLES),
    ("/api/users/*", ADMIN_ROLES),
    ("/api/admin/*", ADMIN_ROLES),
    ("/api/storage/*", ADMIN_ROLES),

    # Inspection workflow.
    ("/api/audits", INSPECTOR_ROLES),
    ("/api/audits/*", INSPECTOR_ROLES),
    ("/api/deficiencies", INSPECTOR_ROLES),
    ("/api/deficiencies/*", INSPECTOR_ROLES),

    # Field technician workflow. Technicians can update equipment and complete
    # assigned tasks, but cannot create/delete master records.
    ("/api/equipment/*", TECHNICIAN_ROLES),
    ("/api/tasks/*/complete", TECHNICIAN_ROLES),
)


def roles_for_write_path(path: str):
    """Return the allowed roles for a state-changing API path."""
    for pattern, roles in PATH_ROLE_RULES:
        if fnmatch(path, pattern):
            return roles
    return MANAGER_ROLES


def can_write(role: str | None, path: str) -> bool:
    return role in roles_for_write_path(path)


def can_manage_users(role: str | None) -> bool:
    return role in ADMIN_ROLES


def can_manage_storage(role: str | None) -> bool:
    return role in ADMIN_ROLES
