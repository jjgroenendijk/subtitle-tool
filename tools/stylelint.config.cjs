/* Stylelint configuration for the project-owned web UI CSS under
 * src/subtitle_tool/web/static/css/. This is local git-hook tooling only: it is
 * run through a single pinned `npx` command (see scripts/pre-commit/40-css.sh
 * and scripts/pre-push/40-css.sh), not added to package.json and not wired into
 * CI. Vendored assets under static/vendor/ are never linted as project CSS.
 *
 * The config is intentionally self-contained and does not `extends` a shared
 * config package. The hooks run Stylelint through an ephemeral `npx` install,
 * and Stylelint resolves `extends`/`plugins` relative to this file's directory,
 * where an npx-installed config package is not visible. Listing native rules
 * directly keeps the single pinned `npx stylelint` command working without a
 * second package or a brittle --config-basedir path.
 *
 * The rules below are correctness-focused: they catch real defects (invalid
 * hex, unknown properties/units/selectors, duplicate or overridden
 * declarations) without reformatting the intentional, pre-existing house style,
 * so the CSS split stays a structure-only refactor.
 */
module.exports = {
  rules: {
    "color-no-invalid-hex": true,
    "comment-no-empty": true,
    "no-duplicate-at-import-rules": true,
    "no-duplicate-selectors": true,
    "no-empty-source": true,
    "no-invalid-double-slash-comments": true,
    "no-invalid-position-at-import-rule": true,
    "block-no-empty": true,
    "declaration-block-no-duplicate-properties": [
      true,
      { ignore: ["consecutive-duplicates-with-different-values"] },
    ],
    "declaration-block-no-shorthand-property-overrides": true,
    "font-family-no-duplicate-names": true,
    "function-calc-no-unspaced-operator": true,
    "function-linear-gradient-no-nonstandard-direction": true,
    "shorthand-property-no-redundant-values": true,
    "at-rule-no-unknown": true,
    "media-feature-name-no-unknown": true,
    "property-no-unknown": [true, { ignoreProperties: ["-webkit-backdrop-filter"] }],
    "selector-pseudo-class-no-unknown": true,
    "selector-pseudo-element-no-unknown": true,
    "selector-type-no-unknown": true,
    "unit-no-unknown": true,
  },
};
