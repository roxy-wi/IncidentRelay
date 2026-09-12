## Backend changes policy

Any backend code change must be covered by tests.

When changing backend logic:
- add new tests for new behavior;
- update existing tests for changed behavior;
- do not remove failing tests unless the tested behavior was intentionally removed;
- if a backend change does not need tests, explain why in the pull request.

## Contributor License Agreement

IncidentRelay uses a Contributor License Agreement so that contributions can be distributed under the project's public source license and, where applicable, under separate commercial terms.

Before a pull request can be merged, each contributor must read [CLA.md](CLA.md) and include the following statement in the pull request description:

`I have read and agree to the IncidentRelay Contributor License Agreement (CLA.md).`

Do not merge a contribution until the contributor has expressly accepted the CLA.
