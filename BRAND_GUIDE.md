# Campus Fire ERP — Brand & UI System

## Identity
Campus Fire ERP is the operational workspace for campus fire safety, compliance, inspections, equipment, permits and documentation. The identity should communicate protection, reliability and clarity — not emergency response or alarm marketing.

The custom mark combines:
- A protective shield for safety and compliance.
- A restrained flame as the fire-safety reference.
- A simple building silhouette for the campus context.

Primary asset: `app/static/img/campus-fire-mark.svg`.

## Palette
| Token | Dark | Light | Purpose |
|---|---|---|---|
| Background | `#101C2C` | `#F4F6F8` | Main workspace |
| Surface | `#17283A` | `#FFFFFF` | Cards and panels |
| Primary | `#22B8B0` | `#087F82` | Primary actions and active navigation |
| Gold | `#D6B46A` | `#B18A3C` | Restrained premium accent |
| Text | `#EDF4F7` | `#17283A` | Primary text |

Status colors remain semantic and distinct from the brand accent.

## Typography and layout
Use the system font stack already defined in the design system; this avoids external font dependencies and keeps Hebrew rendering reliable. Keep RTL direction, clear heading hierarchy, consistent 4px-based spacing, rounded but restrained surfaces, and visible focus states.

## Adaptive themes
The existing theme switch persists the user's choice in `localStorage` under `erp-theme`. Both themes must retain readable contrast. Brand components must use design tokens rather than hard-coded theme-specific colors.

## Entry experience
The animated brand intro appears on the unauthenticated login page before the credentials form, once per browser tab session. It includes a skip action and respects `prefers-reduced-motion`. Successful login navigates to the authenticated application, whose shell does not include or replay the intro. Authenticated users visiting `/login` are redirected to the application.

## Implementation constraints
- No paid fonts, icon services, scripts, or hosted dependencies.
- Preserve all existing routes, data, API behavior and business workflows.
- Do not place sensitive data, certificates, or user-entered form values in the intro or brand assets.
- Keep all operational pages responsive and usable on mobile.
