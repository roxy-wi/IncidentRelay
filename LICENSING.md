# IncidentRelay licensing

IncidentRelay uses a source-available licensing model designed to keep
self-hosting broadly available while reserving hosted/managed IncidentRelay
services for commercial licensing.

## Community license

The current IncidentRelay source distribution is offered under the Elastic
License 2.0 (ELv2), SPDX identifier `Elastic-2.0`.

The canonical ELv2 text is published by Elastic at:
https://www.elastic.co/licensing/elastic-license

An SPDX reference is available at:
https://spdx.org/licenses/Elastic-2.0.html

ELv2 is source-available, but it is not an OSI-approved Open Source license.

## Typical permitted uses

Subject to the complete ELv2 terms, typical permitted uses include:

- running IncidentRelay internally in your own organization;
- modifying IncidentRelay for your own internal use;
- evaluating, testing, and developing against IncidentRelay;
- redistributing IncidentRelay subject to ELv2 requirements;
- a consultant installing or operating IncidentRelay for a customer where the
  customer is using it internally and the consultant is not offering
  IncidentRelay itself as a hosted product to multiple third parties.

## When a commercial license is required

A separate commercial agreement is required when you want rights that are not
granted by ELv2. The primary example is offering IncidentRelay, or a service
that exposes a substantial set of IncidentRelay features or functionality, to
third parties as a hosted or managed service.

Examples include:

- IncidentRelay-as-a-Service;
- a hosted incident-management product that substantially exposes the
  IncidentRelay UI, APIs, workflows, or feature set to customers;
- a managed multi-tenant IncidentRelay offering;
- a white-label hosted IncidentRelay service;
- another hosted or managed offering where commercial rights beyond ELv2 are
  needed.

A commercial license may also be used for negotiated OEM, redistribution,
branding, support, indemnity, warranty, or other enterprise rights.

See `COMMERCIAL_LICENSE.md` for the commercial licensing process.

## What is not automatically a hosted IncidentRelay service

Using IncidentRelay as an internal component of a larger service does not by
itself mean that the larger service is prohibited. The controlling terms are
the ELv2 terms, including whether third-party users are given access to a
substantial set of IncidentRelay features or functionality.

When a proposed deployment is close to that boundary, obtain written licensing
confirmation before launching the service.

## Historical MIT releases

IncidentRelay versions and copies that were already released under the MIT
License remain licensed under the MIT License that accompanied those copies.
This licensing change does not revoke previously granted MIT rights.

The current repository and future releases can use different licensing terms,
but an old MIT-licensed copy cannot be retroactively converted into ELv2 for
people who already received it under MIT.

## Contributions

New contributions are accepted only under the contributor terms in `CLA.md`.
Those terms are intended to ensure that IncidentRelay can continue to be
published under ELv2 while also being offered under separate commercial terms.

Contributors retain ownership of their contributions but grant the project the
rights described in the CLA, including the rights needed for sublicensing and
commercial licensing.

## Third-party dependencies

Third-party dependencies and vendored components retain their own licenses.
Nothing in IncidentRelay's licensing files changes the license of third-party
software.

## Trademarks

A software license does not automatically grant rights to project names,
logos, service marks, or other trademarks except to the extent required by
applicable law or expressly stated in a separate agreement.

## Questions and commercial licensing

For a proposed SaaS, hosted, managed, OEM, white-label, or other commercial use,
contact the IncidentRelay copyright holder through the project repository before
launching the offering.

A signed commercial agreement should identify the licensor and licensee by
legal name and should state the exact rights granted, fees, term, support (if
any), liability terms, governing law, and termination terms.
