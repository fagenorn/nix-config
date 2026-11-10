# Suite runner job count, issue 604

On a 10-CPU Mac the full suite took 923 s at 4 jobs and 473 s at 8, all members passing.

The decision that rests on this measurement is [ADR-delivery-006](../areas/delivery/adr/006-suite-members-run-in-parallel.md).
