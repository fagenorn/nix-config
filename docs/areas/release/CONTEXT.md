---
area: Release
budget: 200 lines
---

# Release

Release takes a verified tip to production through one declared profile and a fixed driver. The transaction core records every step, and adapters turn each step into an effect on a real service.

## Language

**Activation unit**:
The thing a release activates on a host or service, such as a launchd agent or a deployed service. A profile names its activation units and the adapter that activates each.

**Adapter**:
The closed, registered module that performs and observes one kind of release step against a real system. An adapter returns typed results and carries no retry or ordering policy of its own.
_Avoid_: plugin, driver

**Candidate**:
The commit that a release proposes to publish, read from the open pull request into the default branch and the tip it was compared against. A candidate that is stale or behind is refused.
_Avoid_: release commit

**Publication-free profile**:
A release profile whose publication is `none`: it declares its target, requirements and checks but publishes nothing.

**Receipt**:
The durable record that a transaction step took effect, kept in the transaction state. Receipts, hazard markers and later observations let recovery tell what was done.
_Avoid_: log entry

**Release profile**:
One authored entry of the project's `release` member: the target, requirements, publication actions and checks for releasing a project one way.
_Avoid_: release config

**Transaction**:
The unit of release state the transaction core stores under a closed schema and lifecycle, in one state file with fenced writes. Only the release driver opens one.
_Avoid_: run, job
