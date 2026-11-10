# ADR-release-002 — The release driver is the transaction core's only caller

- **Status:** accepted
- **Decided in:** issue 689, #128

## Context

ADR-release-001 made attempts the core's first consumer and ship-release its second. The attempt lifecycle and the helpers that wrote it were retired by issue 689, which left the core with one caller.

## Decision

The core stays, with its closed schema, fenced custody, write-intent protocol, proof and recovery plans and terminal receipts, as the release driver's store. The release driver (#128) is its only caller, and the core has no command-table row of its own.

## Consequences

- The core carries machinery sized for more than one consumer; a change to it is judged against the release driver alone.
- Nothing else may open a transaction, so the library surface needs no compatibility promise beyond that caller.
