# Campus Fire ERP — Workbook-first product redesign

## Product direction

The operational source of truth is the fire-safety work plan supplied by the user. The application should be organized around work, assets, compliance evidence and submission readiness—not around disconnected CRUD pages.

The existing database and integrations remain in place unless a separately reviewed migration is required. Existing records, uploaded documents, fire-form templates and mappings must not be deleted or silently rewritten.

## Primary navigation and information architecture

1. **תמונת מצב** — organization-wide action center: overdue work, deadlines in the next 7/30 days, unresolved critical findings, approvals waiting for review, documents requiring validity review, and submission readiness by case.
2. **תוכנית עבודה** — canonical work-plan table and saved views: all, overdue, due soon, open, waiting for approval, completed, grouped by week, asset, domain, owner and case number.
3. **נכסים ותיקים** — one workspace per asset/building, with case numbers, audit references, location hierarchy, work items, documents, equipment and submission history.
4. **ליקויים ודרישות** — inspection findings and corrective actions, with severity, source report, owner, deadline, evidence and closure approval.
5. **טפסים ואישורים** — fire-form templates, mapping readiness, required form numbers, certificates, validity and print packages.
6. **הגשות לרשות** — submission packages grouped by case, with checklist, covering letter, submitted items, missing items, submission date and authority response.
7. **ספקים ואנשי מקצוע** — contractors, responsible contacts, specialties, licenses, quotes, planned work and linked approvals.
8. **מסמכים וראיות** — searchable document register, Gemini analysis, validity evidence, versions and asset/case relationships.
9. **ביקורות וציוד** — audits, recurring inspections, equipment status and deficiencies.
10. **דוחות ובקרה** — progress by asset, domain, owner, week, form, case and deadline.

## Canonical work-plan fields

Keep the supplied spreadsheet's order and labels in the main work table:

1. שלב / שבוע
2. משימה / נושא מרכזי
3. נכס רלוונטי
4. מס' תיק
5. מס' טופס להגשה
6. הגורם האחראי
7. תאריך יעד לביצוע
8. סטטוס נוכחי
9. הערות ודגשים
10. תאריך ביצוע בפועל
11. ימים ליעד
12. התראת מועד
13. תחום

Derived fields must not become manually maintained duplicate facts:
- ימים ליעד = calendar-day difference between target date and the organization's local current date.
- התראת מועד = הושלם / באיחור / קרוב למועד / תקין / ללא תאריך יעד.
- A completed item is not overdue even if its original target date has passed.
- A proposed target date remains explicitly marked as proposed until approved; never silently treat it as a confirmed commitment.
- Keep the original note/update chronology intact. New updates should append dated events, not replace old notes.

## Status model

The source sheet contains distinct meanings that must remain distinguishable:
- לביצוע
- בטיפול
- ממתין לאישור
- הושלם
- בוטל

Do not collapse "ממתין לאישור" into "בטיפול" in the user interface. If the existing Task status enum cannot represent it safely, add an explicit workflow status through a reviewed migration and update all status-dependent calculations and tests.

## Data integrity and migration rules

- Treat the supplied rows as the authoritative baseline for the initial work-plan import.
- Preserve source row identity and the original text, including legal/engineering caveats, quoted authority notes and historical updates.
- Import must be idempotent and versioned. A repeated sync must update the same source records rather than duplicate them.
- Do not delete legacy tasks. Mark or exclude legacy import batches from the new work-plan view only after an auditable mapping.
- Keep existing asset IDs, case numbers, document relationships, organization tenancy and RLS boundaries.
- Match a document or AI report to an asset/case only on strong evidence; ambiguous matches require review.
- Preserve the distinction between a document being received, valid, approved and actually submitted.
- Do not infer a fire-code requirement from a note. Legal/engineering arguments remain flagged for qualified professional/authority validation.

## Interaction and visual rules

- Hebrew RTL throughout, with a consistent compact enterprise design system.
- Work table is a true dense data workspace: sticky headers, clear row hierarchy, readable notes, inline status updates, fast search, filters, sorting, saved views and bulk actions with confirmation.
- Use a details panel only for secondary history/evidence; never hide primary spreadsheet fields behind it.
- On narrow screens, show an intentional card/table hybrid with key fields first and no clipped controls.
- Every status uses text plus a restrained color cue; color alone never conveys meaning.
- Use the repository's local Lucide sprite and local CSS assets only. No paid SaaS, external icon/font CDN or runtime dependency.
- Avoid duplicate navigation, repeated headings and redundant cards.

## Delivery sequence

### Phase A — work-plan foundation
- Rebuild the work-plan screen around all 13 columns.
- Replace the legacy hard-coded importer with a versioned source dataset reflecting the supplied rows, dates, completion dates, status and domain.
- Add safe idempotent reconciliation and tests for dates, source row identity, status mapping, note preservation and repeated import.
- Verify every row against the user's supplied source before enabling production sync.

### Phase B — asset and case workspaces
- Make each case/asset a first-class workspace.
- Link tasks, deficiencies, forms, documents, contractors and audits through explicit relationships.
- Provide a cross-asset view for multi-site certificates and submissions without duplicating source documents.

### Phase C — approvals and submission operations
- Add submission package checklists and missing-evidence logic.
- Distinguish received / reviewed / approved / submitted / authority response.
- Link each submitted form to its case, asset and evidence.

### Phase D — organization dashboard and reports
- Derive KPIs from the canonical work plan and verified evidence.
- Drill from every KPI into the exact records behind the number.
- Expose data gaps and uncertain matches separately from compliant/complete items.

### Phase E — full visual system and regression
- Align every operational module to the new information architecture.
- Verify desktop, tablet and mobile layouts, RTL, keyboard accessibility and print layouts.
- Run full unit, integration, fire-form, migration and security/tenant-isolation suites before merge and production deploy.

## Current implementation note

PR #60 is the first implementation slice: it rebuilds the task/work-plan surface and expands the tracking API contract. The legacy importer still needs to be reconciled with the current 13-column source data before the production records can be considered synchronized. Do not merge or deploy this slice as a completed end-to-end redesign until CI passes and the data-import phase is complete.
