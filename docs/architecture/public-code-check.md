# Public code reachability check

Run `python tools/check_dead_code.py` after installing `requirements-dev.txt`.
The Quality workflow runs this as a blocking check on pull requests and release
branches. It uses Vulture at 60% confidence to identify unused public functions
and classes defined at module level in `app`.

Application code, tests, tools, Docker helpers, integration examples (including
`docs/examples`), and Python entry points at the repository root provide references.
Temporary checkouts and generated files under hidden directories are excluded.
Flask route, error, context and request hook decorators are recognized as
registrations. Ordinary decorators such as caching do not suppress findings.
The check parses Python without importing the application or opening its database.

Vulture matches identifiers rather than proving runtime reachability. A finding
requires review of references, dynamically built names, registrations, templates
and compatibility promises before deletion. The gate does not cover private
helpers, nested definitions, framework methods, ORM fields or variables; the full
nightly Vulture scan reports those separately as advisory findings.

`tools/dead_code_allowlist.json` contains path-and-name exceptions with concrete
reasons. Currently it preserves the index helper used in generated migration
source and the explicitly compatible legacy audit reader. Exceptions without
reasons, or entries that no longer correspond to a reported definition, fail the
check. Do not add broad file exclusions or suppress an entire class of new code
to make the gate pass.

`tests/quality/test_dead_code_checker.py` verifies unused definitions, registered
handlers, plugin references, test callers, temporary checkouts and parse errors.
Changes that remove unused wrappers must also run the existing behavior tests
for their active replacement paths.
