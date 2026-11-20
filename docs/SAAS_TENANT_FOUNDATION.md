# SaaS Tenant Foundation

## Status

This release adds the first organization record, organization memberships, and an organization key to every business-data table. Existing records are assigned to one legacy organization; existing user accounts are given an active membership with their current role. No records are deleted or rewritten beyond this ownership backfill.

The ORM layer applies organization filters to business-table reads and bulk ORM writes. New and modified rows are bound to the organization stored on the database session. Foreign-key references to another organization's rows are rejected before commit.

## Existing production data

The migration is additive:
- Creates `organizations` and `organization_memberships`.
- Creates one legacy organization.
- Creates one membership for each existing user, preserving the user's current role.
- Adds `organization_id` to all 16 business-data tables and assigns existing rows to the legacy organization.
- Adds indexes and PostgreSQL foreign keys for the new ownership columns.

The existing user identity table remains global in this foundation release. The current login flow remains attached to the legacy organization. The migration does not create a public sign-up flow or expose organization creation.

## Security boundary and release gate

This is a foundation, not a declaration that the product is already ready for external multi-tenant customers. Before enabling customer onboarding, the next release must complete:
1. Organization creation, invitation and membership switching with per-organization roles.
2. Tenant-scoped storage paths and document download authorization.
3. Audit-log, notification, search, report and background-task tenant scoping.
4. Composite uniqueness and relationship constraints where uniqueness is tenant-local.
5. A cross-tenant API test matrix covering every blueprint and direct-ID access path.
6. Backup/restore rehearsal and operational monitoring.

Do not enable public registration or create customer tenants until that release passes its isolation tests.

## Current infrastructure constraints

The deployed web service is on Render's free plan and uses one instance. Its rate limiter currently falls back to process-local memory because no shared Redis endpoint is configured. The application database is the Neon `campus-fire-erp` project on the free tier. The current database connection role is `neondb_owner` and has `BYPASSRLS=true`; therefore PostgreSQL row-level security policies would not constrain this connection. Before onboarding external tenants, provision a separate least-privilege runtime role without `BYPASSRLS`, enable and force RLS on tenant-owned tables, verify storage object policies, and update the Render connection string through a reviewed secret change. These constraints are acceptable for controlled pilot development, but not a claim of production-grade high availability, contractual backups, or horizontal scaling. No paid services are introduced by this release.
