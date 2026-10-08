# Worked reuse analysis

A requirement needs a new input path to apply the same title-normalization rule already used by the editor.

## Bad addition

Add `normalize_import_title` beside `normalize_editor_title`, copy the trim/limit logic, and write tests against each implementation separately. Later a Unicode rule changes in one function. Both unit suites can still pass because their fixtures differ, while product behavior diverges.

## Better decision

Inspect the authoritative domain type and its constructor. Route both editor and import boundary conversion through the same constructor. Keep the input-specific error context in each adapter, but retain one implementation of the normalization invariant. Add tests that both entry paths produce the same accepted value and rejection semantics.

This is a modification when the existing type already owns the rule. If it does not, a focused extraction may be warranted. The plan must classify the actual work and preserve the requested category order, rather than calling every new file a modification.

## Reuse record

| Item | Recorded result |
|---|---|
| Requirement | Stable ID of the shared input rule |
| Searched | Domain value type, editor conversion, import adapter, existing tests |
| Existing owner | Actual symbol and path, verified by callers |
| Option 1 | Extend existing constructor: one invariant, minimal caller changes |
| Option 2 | New import validator: rejected because it duplicates semantics |
| Option 3 | Generic validation framework: rejected because no requirement needs configurable rules |
| Decision | Reuse the owner; preserve adapter-specific error labeling |
| Verification | Same boundary fixtures through editor and import; maximum-length and Unicode cases |

## Where duplication can be acceptable

Two adapters can each map different framework errors into the approved domain error. If their inputs and meanings differ, extracting a universal function may increase coupling. Prefer explicit small mappings over a generic abstraction with flags for every unrelated transport.

## Phase review

Review the actual diff, not just the rationale. Check that a second owner was not introduced in a helper file, that repeated boundary conversions still call the canonical validator, and that the test oracle does not duplicate the production algorithm. Count duplicated rules and public surface growth; do not equate fewer lines with better design.
