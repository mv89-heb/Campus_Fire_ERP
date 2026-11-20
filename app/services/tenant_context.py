"""Organization-aware ORM scoping and write-time tenant integrity checks.

All business-table ORM reads and bulk writes are constrained to the organization
bound to the current SQLAlchemy session. Cross-organization references and
attempts to move rows between organizations are rejected before flush.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import (
    Zone, SystemRequirement, Document, Site, Building, Floor, Area,
    Supplier, Equipment, Task, Audit, Deficiency, DocumentHistory,
    Notification, AuditLog, FireFormTemplate,
)

TENANT_MODELS = (
    Zone, SystemRequirement, Document, Site, Building, Floor, Area,
    Supplier, Equipment, Task, Audit, Deficiency, DocumentHistory,
    Notification, AuditLog, FireFormTemplate,
)
TENANT_MODELS_BY_TABLE = {model.__tablename__: model for model in TENANT_MODELS}


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
