# Campus Fire ERP — UI Toolchain & Redesign Plan

## Objective

Deliver a consistent, premium, accessible Hebrew RTL operational interface across the existing Campus Fire ERP without replacing its Flask/Jinja application architecture, changing business rules, or risking tenant data.

## Current verified baseline

- Application: Flask + Jinja templates + browser JavaScript.
- Shared authenticated shell: `app/templates/_shell.html`.
- Shared visual tokens/components: `app/static/css/design-system.css`.
- Existing templates inherit the shared shell; the current page inventory includes dashboard, permits, fire forms, audits, documents, equipment, sites, suppliers, tasks, reports, settings and user administration.
- The repository currently has no `package.json`, Tailwind build pipeline, or Lucide dependency.
- The existing design system and brand guide are already present. They are the starting point, not a reason to introduce a second competing design system.

## Tool responsibilities

### Figma / Stitch
Use as the design source of truth for screen layouts, interaction states, responsive variants and component specifications. Exported designs are references; production implementation must use the repository's actual data contracts and routes.

### v0.dev
Use for rapid component and layout exploration only. Generated React/Next.js output must not be pasted wholesale into this Flask/Jinja application. Rebuild or adapt the approved patterns as Jinja-compatible HTML, CSS and small browser-side JavaScript components.

### Canva
Use for brand collateral, training graphics and approved static visual assets. Operational icons must remain vector-based and consistent; Canva is not the source of truth for interactive UI components.

### Tailwind CSS
Introduce only as a local build-time dependency if the Render build pipeline can be updated and verified. Scope it with a dedicated prefix (for example `tw-`) and disable Preflight so it cannot reset or damage existing Jinja pages. Keep the existing CSS custom properties as the single source of truth for brand colors, semantic statuses, typography and theme behavior. Do not load Tailwind from a CDN in production.

### Lucide Icons
Use a pinned, locally bundled Lucide icon set. Replace decorative emoji in navigation and primary controls with consistent accessible SVG icons, while preserving meaningful emoji/text in user content and records. Icons must have accessible labels where they convey meaning.

### n8n / Make
Treat automation platforms as optional external integrations, not application runtime dependencies. Start with low-risk notifications and reminders. Any webhook must use server-side secrets, tenant-scoped authorization, signature verification where supported, idempotency, retries with limits, and audit logging. Never send certificates, personal data, document contents or cross-tenant data to an automation service by default. Do not put safety-critical approvals or compliance state changes exclusively in an external automation.

## Non-negotiable engineering constraints

1. Preserve Flask routes, API contracts, database schema, existing records, authentication, CSRF, permissions and tenant isolation.
2. No production data migration or destructive cleanup as part of a visual redesign.
3. No paid service or hosted runtime dependency without explicit approval.
4. Hebrew RTL must be correct at every breakpoint; tables and forms must remain usable on mobile.
5. Every interactive control must perform a real supported action. Do not create decorative or fake controls.
6. Missing or stale source data must be displayed as unknown/missing, never silently interpreted as compliant.
7. Fire-form temporary values, signatures and professional certificate images must follow the existing non-persistence requirements.
8. No external CDN dependency for core CSS, JavaScript, fonts or icons.

## Implementation sequence

1. **Baseline audit:** map all routes/templates, identify duplicated styles, inspect responsive behavior and record existing UI defects.
2. **Design foundation:** consolidate tokens, typography, spacing, focus/keyboard states, semantic badges, tables, forms, dialogs, loading/error/empty states and icon usage.
3. **Application shell:** refine sidebar grouping, top bar, search, notifications, mobile navigation and active-route behavior.
4. **Operational dashboard:** show only metrics supported by reliable data; make missing data explicit.
5. **Operational screens:** standardize tables, filters, sorting, bulk actions and responsive detail patterns.
6. **Documents and fire forms:** improve confidence/verification, source-to-field review, mapping clarity and PDF preview while preserving temporary-data handling.
7. **Quality gate:** run Python compile/tests, frontend asset build, accessibility/RTL checks, responsive checks and the existing fire-form CI. Open a PR and merge only after checks pass and the final diff is reviewed.

## Deployment gate

Repository changes may be prepared on a feature branch. Render build/deploy configuration must not be changed until the correct Render workspace and service are explicitly confirmed. A successful GitHub check is not proof of a successful production deployment.
