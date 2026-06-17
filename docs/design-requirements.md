# Subtitle Tool — Design Requirements

Requirements for the visual and interaction design of the web UI. This document defines the intended
direction so a later refresh has a single reference to build against; it does not implement the
redesign. It is the source of truth for the look and feel, the way `functional-requirements.md` is
for behavior and `technical-requirements.md` for implementation constraints. Where a behavior is
already described in those documents, this one only adds the visual rules.

The direction is a translucent, layered interface: a stable backdrop with content sitting on it, and
a thin set of control surfaces that read as frosted panes floating above. It stays simple, crisp,
and utilitarian. The aesthetic serves legibility and a sense of depth, never decoration for its own
sake.

## Layering Model

The UI has two functional layers, and every element belongs to exactly one.

- Content layer: the data the tool exists to show — the library table, job history, job-detail file
  lists, configuration form values. This is the primary layer. It is opaque or near-opaque,
  high-contrast, and never sacrifices readability for effect.
- Control layer: navigation, toolbars, buttons, filters, status surfaces, overlays, and focused
  actions. This is where the translucent treatment lives. It reads as a distinct pane sitting above
  the content so the user can tell controls from data at a glance.

The backdrop sits beneath both: a fixed, low-contrast page background (a faint gradient) that the
control layer blurs over to produce depth. The backdrop is deliberately quiet so blurred panes have
something to react to without competing with content.

Depth ordering, front to back: focused overlays and popovers, then sticky navigation and toolbars,
then content panels, then the page backdrop. Keep the number of distinct depth levels small; a flat
hierarchy is easier to read than a deep stack.

## Material and Depth

The frosted material is built from five ingredients used together, never one in isolation:

- Translucency: a partially transparent surface fill so the backdrop shows through. Translucency
  alone is not the effect.
- Background blur: a `backdrop-filter` blur (with a light saturation lift) behind the surface. The
  blur is what makes a pane read as glass rather than as a flat tint. A translucent surface without
  blur is not permitted in the control layer.
- Subtle highlight: a faint light edge or inner top highlight that suggests a catching of light and
  lifts the pane off the backdrop.
- Border: a thin hairline border that defines the pane's edge crisply against changing content
  behind it.
- Shadow: a soft drop shadow that seats the pane above the layer beneath it.

Depth comes from combining a hairline border, a subtle highlight, and a soft shadow — not from heavy
blur or strong tint. Readability over changing content is the hard constraint: because the backdrop
and any content beneath a pane can vary, every translucent surface must keep text and controls
legible regardless of what shows through. When a surface carries text, raise its opacity toward
opaque rather than thinning it for a stronger glass look. Legibility wins over the effect every
time.

## Where the Material Is Allowed, Forbidden, and Falls Back

Allowed (control layer):

- Sticky navigation rail and its mobile top-bar form.
- Toolbars, action bars, and the sticky table header row.
- Buttons, form controls, and input surfaces.
- Overlays, popovers, dropdowns (for example the library column picker), and focused or modal
  actions.
- Status and notice surfaces.

Forbidden (content layer and large surfaces):

- Dense content tables and their body rows. The table body stays on a near-opaque surface; only its
  header row and surrounding toolbar may use the material.
- Large reading surfaces and long text blocks.
- The page backdrop itself (it is the thing being blurred, not a blurred pane).
- Any surface stacked directly on another translucent surface (see Anti-Patterns).

Fallback when legibility is at risk: if blur is unsupported, disabled by the user, or the content
behind a pane would reduce contrast below the accessible threshold, the surface must degrade to a
solid (opaque) fill of the same color family. The layout, borders, and shadows stay; only the
transparency is dropped. Treat the opaque form as the floor the design must always remain usable at,
not a rare edge case — design the solid version first and add translucency as an enhancement.

## Geometry

Geometry stays crisp. This is a deliberate, non-negotiable departure from the soft, rounded look the
translucent treatment is usually paired with.

- Default corner radius is zero. Panels, cards, tables, inputs, and buttons have square corners and
  sharp edges.
- A very small radius (no more than 2px) is permitted only where a hard 90-degree corner would look
  like a rendering defect at a given size; it is never large enough to read as "rounded."
- Pill, capsule, bubble, and heavily rounded shapes are rejected. Tags, status chips, buttons, and
  toggles are rectangular, not lozenges.
- The only exceptions are native browser controls that the platform rounds on its own (for example a
  default checkbox or range thumb) and any existing project convention already shipped; do not add
  rounding beyond those.

Panel edges are sharp, table and list corners are crisp, and dividers are hairlines. The intended
read is "precise instrument," not "soft card."

## Color and Tint

The palette is mostly neutral. Tint and accent color are reserved for meaning, not for surface
decoration.

Accent or tint is used only for:

- Primary actions (the main button in a context).
- Selected or active state (the current nav link, an active sort column).
- Warnings, errors, and other status that needs to stand out.
- Live progress (a running job, a progress bar).

Everything else — secondary buttons, borders, panel fills, body text, table chrome — stays neutral.
Do not tint every control, and do not let one accent color wash over the whole UI and turn it into a
single-color theme. A glance at a screen should reveal the one or two things that are actionable or
notable by their color, with the rest calm and neutral.

## Motion

Motion is responsive and restrained. It confirms an interaction; it never performs. There are no
elastic, bouncy, springy, or overshooting effects, and nothing oscillates or settles. Transitions
are short and use a plain ease.

- Hover: a quick, subtle change of background or color to confirm the target is interactive.
- Focus: an immediate, clearly visible focus indicator. The indicator's appearance is never animated
  away or delayed.
- Active/press: an immediate, minimal response (for example a slight brightness or background
  shift).
- Loading and live progress: continuous indeterminate or determinate motion is allowed only on the
  element that is actually loading (a progress bar, a spinner on the running job); it does not
  spread to surrounding chrome.
- Expanding and collapsing (details/disclosure, popovers): a short reveal, not a dramatic grow.

Respect reduced-motion preferences (see Adaptive Behavior); under that preference, transitions are
removed or reduced to near-instant.

## Adaptive Behavior

The design adapts to user and system settings rather than imposing one look.

- Light and dark themes: both are first-class, switched by the operating-system color-scheme
  preference (`prefers-color-scheme`). There is no in-app theme toggle or persisted theme state.
  Every color, surface, border, highlight, and shadow value has a defined light and dark form. The
  dark theme is not the light theme with inverted colors; surfaces, highlights, and shadows are
  tuned separately so depth reads correctly on a dark backdrop.
- High contrast: when the platform signals a need for more contrast (for example
  `prefers-contrast: more` or a forced-colors mode), surfaces move toward opaque, borders
  strengthen, and text/background contrast increases. The interface must remain fully usable with
  system-forced colors.
- Reduced transparency: when the platform signals reduced transparency (for example
  `prefers-reduced-transparency: reduce`), translucent surfaces drop to their solid fallbacks and
  blur is removed. This shares the opaque-fallback path described under legibility, so it is the
  same code path, not a separate style.
- Reduced motion: when `prefers-reduced-motion: reduce` is set, transitions and non-essential
  animation are removed or reduced to near-instant; only motion that conveys real state (determinate
  progress) remains, and even that is minimized.

## Design Tokens

Every shared visual value is a named token (a CSS custom property) declared once and referenced
everywhere. The ranges below bound the design; the implementation fixes concrete values within them
and may add tokens, but must not introduce values outside these ranges without revising this
document. Values are grounded in the current stylesheet so the refresh evolves the existing look
rather than restarting it.

Corner radius

- `--radius`: 0 (default for all panels, cards, tables, inputs, buttons).
- `--radius-sm`: 0 to 2px, used only for the rare native-control exception above.
- No radius token exceeds 2px. There is no "pill" or "round" radius token.

Surface opacity (alpha of the translucent fill, before blur)

- Regular control surface: 0.55 to 0.70.
- Recessed/secondary surface: 0.40 to 0.50.
- Strong surface (text-bearing controls, sticky table header, inputs): 0.80 to 0.90.
- Solid fallback: 1.0 (the value used when transparency is dropped).
- Text-bearing surfaces sit at the high end of their range so contrast holds over changing content.

Background blur

- `--blur`: a blur radius of 12px to 20px, paired with a saturation lift of roughly 1.3 to 1.6 (for
  example `blur(16px) saturate(1.5)`).
- One shared blur token is used across the control layer; do not vary blur per component without
  cause.

Borders

- `--border`: a hairline (1px) at low alpha, roughly 0.10 to 0.16 against the surface, for ordinary
  pane edges and dividers.
- `--border-strong`: 1px at roughly 0.20 to 0.26, for inputs and emphasized edges.
- Borders are always 1px hairlines; thickness is not used to create emphasis (use color or a
  left-accent stripe instead).

Shadows

- `--shadow-sm`: a single tight, low-opacity shadow for slightly raised chrome.
- `--shadow`: a two-part shadow (a tight contact shadow plus a softer, larger ambient shadow) for
  panels and overlays that float above content.
- Shadow opacity stays low in light themes and somewhat higher in dark themes so depth reads on
  both. No hard, high-opacity, or colored drop shadows.

Spacing

- A single spacing scale in `rem` steps (for example 0.25, 0.5, 0.75, 1, 1.5, 2) drives padding,
  gaps, and margins. Component spacing references the scale; it does not invent one-off pixel
  values.

Z-index layers

- A small, named set of stacking levels matching the depth ordering: backdrop, content, sticky
  chrome (nav, table header), then overlays/popovers. Components reference these tokens rather than
  writing raw `z-index` integers, so the layer order is defined in one place.

Motion timing

- `--motion-fast`: roughly 80ms to 120ms for hover, focus, and press feedback.
- `--motion`: roughly 120ms to 200ms for reveals and larger state changes.
- Easing is a plain ease (or ease-out); no spring, bounce, or back/overshoot curves. Under reduced
  motion these collapse to near-zero.

## CSS Reuse Requirements

The implementing CSS must centralize shared visual values and reference them, rather than repeating
literals across selectors. This is a hard requirement, not a style preference, because the design
only stays coherent if a color, material, or radius means the same thing everywhere and changes in
one place.

- Colors, surface/material fills, borders, radii, shadows, spacing, z-index levels, and motion
  timings are each declared once as a design token (CSS custom property) and referenced throughout.
- The same color, material value, border, radius, shadow, spacing step, or transition must not be
  hard-coded as a literal in more than one selector. If a value appears in two places, it is a
  token.
- Light/dark and high-contrast/reduced-transparency variants are expressed by redefining the tokens
  under the relevant media query, so component rules stay identical across themes and only the token
  values change.
- A one-off literal is allowed only for a value that is genuinely unique to a single rule and
  carries no shared meaning; anything reused, or likely to be reused, is a token.

## Anti-Patterns

These are explicitly rejected:

- Stacked translucent surfaces: a frosted pane directly on top of another frosted pane.
  Blur-over-blur muddies both and destroys depth. A control on a translucent toolbar uses an opaque
  or solid treatment, not a second glass layer.
- Low-contrast text over busy content: text placed on a translucent surface where the content behind
  it drops contrast below the accessible threshold. Raise opacity or fall back to solid instead.
- Decorative blur blobs: floating colored shapes, gradient orbs, or ambient "glow" decorations used
  purely for atmosphere.
- Rounded-card-heavy layouts: a page built from many large, soft, rounded cards. This conflicts
  directly with the crisp-geometry requirement.
- Pill/capsule UI: lozenge buttons, capsule tags, and bubble toggles.
- Repeated one-off CSS values: the same color, material, border, radius, shadow, spacing, or
  transition pasted across selectors instead of a shared token.
- Marketing-style hero composition: oversized hero banners, splash imagery, large centered
  call-to-action layouts, or landing-page framing. This is a utility dashboard, not a product
  landing page.
- Single-color wash: tinting most of the UI one accent color (see Color and Tint).
- Effect over legibility: any choice that strengthens the glass look at the cost of readability.

## Implementation Boundaries

The design must fit the existing stack and not imply a different one.

- The UI stays server-rendered Jinja templates over FastAPI as the source of truth, with a thin
  Alpine.js layer for page-local interactivity only, exactly as `technical-requirements.md`
  describes. This document does not change that model.
- No single-page-application architecture, no client-side router, and no client-owned view state
  beyond the existing transient page-local Alpine components.
- No frontend bundler, build step, or CSS framework is introduced. Styling stays in the single
  vendored stylesheet using plain CSS and custom properties.
- The design is achievable with CSS the browser applies directly: custom properties for tokens,
  media queries for theme and accessibility preferences, `backdrop-filter` for the material, and
  standard transitions for motion.
- Accessibility is part of the design, not an afterthought: visible focus, keyboard operability,
  accessible contrast, and the adaptive behaviors above are requirements, not enhancements.
