# @agit8or/connect (TypeScript reference SDK)

Sign / verify / token / webhook functions of the Agit8or Connect protocol
`agit8or-connect/1` (see `docs/agit8or-connect/PROTOCOL.md`), written with
`node:crypto` only — no npm dependencies. The source uses erasable TypeScript
syntax only, so Node 22.18+ runs it directly (type stripping); a NestJS app can
compile it with its normal `tsc` build.

    node --test test/*.test.ts

The tests verify the shared vectors in `docs/agit8or-connect/test-vectors/`,
the same files the Python SDK verifies. Passing them is the interop proof.

Protocol revision 1.1 (`docs/agit8or-connect/PROTOCOL-1.1.md`, optional Quick
Connect extensions) is in the same file, after the v1 functions:
`buildInvitation` / `verifyInvitation`, `buildAccept` / `verifyAccept`,
`buildExchange` / `verifyExchange`, `qcTranscriptHash` / `qcSas`,
`negotiateExtensions` / `checkNoDowngrade`, `normalizeNet` / `checkNet`,
`checkBase` / `checkRedirectUri`, `buildProbeResponse` /
`validateProbeResponse`. `test/qc.test.ts` verifies `test-vectors/qc-*.json`.
