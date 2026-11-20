"""Organization-aware ORM scoping and write-time tenant integrity checks.

All business-table ORM reads and bulk writes are constrained to the organization
bound to the current SQLAlchemy session. Cross-organization references and
attempts to move rows between organizations are rejected before flush.
"""
from sqlalchemy import event, text
from sqlalchemy.orm import Session, with_loader_criteria
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.models import (
    Zone, SystemRequirement, Document, Site, Building, Floor, Area,
    OrganizationMembership, LEGACY_ORGANIZATION_ID,
    Supplier, Equipment, Task, Audit, Deficiency, DocumentHistory,
    Notification, AuditLog, FireFormTemplate,
)

TENANT_MODELS = (
    Zone, SystemRequirement, Document, Site, Building, Floor, Area,
    Supplier, Equipment, Task, Audit, Deficiency, DocumentHistory,
    Notification, AuditLog, FireFormTemplate,
)
TENANT_MODELS_BY_TABLE = {model.__tablename__: model for model in TENANT_MODELS}
DOCUMENT_TOKEN_SALT = "campus-fire-document-access-v1"
DOCUMENT_TOKEN_MAX_AGE = 300


def document_access_token_valid(token, document_id, secret_key):
    if not token or not secret_key:
        return False
    try:
        serializer = URLSafeTimedSerializer(secret_key, salt=DOCUMENT_TOKEN_SALT)
        payload = serializer.loads(token, max_age=DOCUMENT_TOKEN_MAX_AGE)
        return int(payload.get("doc_id")) == int(document_id)
    except (BadSignature, SignatureExpired, TypeError, ValueError, AttributeError):
        return False


def _set_postgres_tenant_settings(connection, organization_id=None, document_id=None):
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(
            "SELECT set_config('app.current_organization_id', :organization_id, true), "
            "set_config('app.allowed_document_id', :document_id, true)"
        ),
        {
            "organization_id": str(organization_id or ""),
            "document_id": str(document_id or ""),
        },
    )


def _restore_postgres_tenant_settings(session, transaction, connection):
    _set_postgres_tenant_settings(
        connection,
        session.info.get("organization_id"),
        session.info.get("allowed_document_id"),
    )


def _unwrap_scoped_session(session):
    # Flask-SQLAlchemy exposes a scoped_session proxy; event/session APIs live
    # on the concrete Session returned by calling that proxy.
    if not hasattr(session, "in_transaction") and callable(session):
        return session()
    return session


def bind_organization(session, organization_id):
    """Bind ORM and PostgreSQL RLS to the active organization for this request."""
    session = _unwrap_scoped_session(session)
    organization_id = str(organization_id)
    session.info["organization_id"] = organization_id
    session.info.pop("allowed_document_id", None)
    if session.in_transaction():
        _set_postgres_tenant_settings(session.connection(), organization_id, None)


def bind_document_access(session, document_id):
    """Allow one signed-link document read without opening the tenant's other rows."""
    session = _unwrap_scoped_session(session)
    session.info.pop("organization_id", None)
    session.info["allowed_document_id"] = str(int(document_id))
    if session.in_transaction():
        _set_postgres_tenant_settings(session.connection(), None, document_id)


class TenantAccessError(Exception):
    """Raised when a request attempts to cross an organization boundary."""


def _apply_organization_scope(execute_state):
    organization_id = execute_state.session.info.get("organization_id")
    if not organization_id:
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return

    statement = execute_state.statement
    for model in TENANT_MODELS:
        statement = statement.options(
            with_loader_criteria(
                model,
                lambda entity: entity.organization_id == organization_id,
                include_aliases=True,
            )
        )
    execute_state.statement = statement


def _validate_tenant_references(session, instance, organization_id):
    mapper = instance.__mapper__

    # Validate relationship objects already attached to the unit of work.
    for relationship in mapper.relationships:
        related = getattr(instance, relationship.key, None)
        related_items = related if relationship.uselist and related is not None else [related]
        if not relationship.uselist:
            related_items = [related]
        for target in related_items or []:
            if isinstance(target, TENANT_MODELS) and target.organization_id not in (None, organization_id):
                raise TenantAccessError("Cross-organization relationship blocked")

    # Validate foreign-key IDs assigned directly in request payloads.
    for column in mapper.columns:
        if column.key == "organization_id":
            continue
        value = getattr(instance, column.key, None)
        if value is None:
            continue
        for foreign_key in column.foreign_keys:
            target_model = TENANT_MODELS_BY_TABLE.get(foreign_key.column.table.name)
            if target_model is None:
                continue
            pending_target = next(
                (
                    item for item in session.new
                    if isinstance(item, target_model)
                    and getattr(item, "id", None) == value
                ),
                None,
            )
            if pending_target is not None:
                if pending_target.organization_id not in (None, organization_id):
                    raise TenantAccessError("Cross-organization relationship blocked")
                continue
            target = (
                session.query(target_model)
                .filter(target_model.id == value)
                .first()
            )
            if target is None:
                raise TenantAccessError("Referenced record is not available in this organization")


def _assign_and_validate_organization(session, flush_context, instances):
    organization_id = session.info.get("organization_id")
    if not organization_id:
        return

    for instance in list(session.new) + list(session.dirty):
        if not isinstance(instance, TENANT_MODELS):
            continue
        current_organization_id = getattr(instance, "organization_id", None)
        if instance in session.new:
            if current_organization_id not in (None, organization_id):
                raise TenantAccessError("Cannot create a record for another organization")
            instance.organization_id = organization_id
        elif current_organization_id != organization_id:
            raise TenantAccessError("Cannot modify a record owned by another organization")

        _validate_tenant_references(session, instance, organization_id)


def install_tenant_guards():
    """Install once on SQLAlchemy's Session base so Flask-SQLAlchemy sessions inherit it."""
    if not event.contains(Session, "do_orm_execute", _apply_organization_scope):
        event.listen(Session, "do_orm_execute", _apply_organization_scope)
    if not event.contains(Session, "before_flush", _assign_and_validate_organization):
        event.listen(Session, "before_flush", _assign_and_validate_organization)
    if not event.contains(Session, "after_begin", _restore_postgres_tenant_settings):
        event.listen(Session, "after_begin", _restore_postgres_tenant_settings)


def resolve_membership(user, organization_id=None, allow_legacy_bootstrap=False):
    """Resolve the active membership; only non-production may repair legacy test/dev accounts."""
    organization_id = organization_id or LEGACY_ORGANIZATION_ID
    membership = OrganizationMembership.query.filter_by(
        organization_id=organization_id,
        user_id=user.id,
        status="active",
    ).first()

    if membership is None:
        if not allow_legacy_bootstrap or organization_id != LEGACY_ORGANIZATION_ID:
            return None
        membership = OrganizationMembership(
            organization_id=LEGACY_ORGANIZATION_ID,
            user_id=user.id,
            role=user.role,
            status="active",
        )
        from app.extensions import db
        db.session.add(membership)
        db.session.flush()
        return membership

    # User.role remains the legacy single-organization source of truth while
    # customer switching is disabled. Never overwrite per-org roles once a
    # user belongs to more than one organization.
    membership_count = OrganizationMembership.query.filter_by(user_id=user.id).count()
    if membership_count == 1 and membership.role != user.role:
        membership.role = user.role
        from app.extensions import db
        db.session.flush()
    return membership
