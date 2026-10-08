---
name: codebase-design
description: Deep-module vocabulary and principles for interfaces and seams. Use when designing a module or seam, or when another skill needs the deep-module vocabulary.
---

# Codebase Design

Design **deep modules**: a lot of behaviour behind a small interface, placed at a clean seam, testable through that interface. The aim is leverage for callers, locality for maintainers and testability for everyone.

## Glossary

Use these terms exactly; never substitute "component", "service", "API" or "boundary".

**Module**: anything with an interface and an implementation, at any scale: function, class, package or tier-spanning slice. _Avoid_: unit, component, service.

**Interface**: everything a caller must know to use the module correctly: the type signature plus invariants, ordering constraints, error modes, required configuration and performance characteristics. _Avoid_: API, signature (both name only the type-level surface).

**Implementation**: the code inside a module. Distinct from **Adapter**: a small adapter can hide a large implementation (a Postgres repo) and a large adapter a small one (an in-memory fake). Say "adapter" when the seam is the topic.

**Depth**: leverage at the interface, the behaviour a caller or test can exercise per unit of interface learned. **Deep**: much behaviour behind a small interface. **Shallow**: an interface nearly as complex as the implementation.

**Seam** _(Michael Feathers)_: a place where behaviour can change without editing in that place; the location of a module's interface. Where the seam goes is its own decision. A **test seam**, as the design and planning skills use the term, is a seam chosen as the boundary verification crosses. _Avoid_: boundary (overloaded with DDD's bounded context).

**Adapter**: a concrete thing that satisfies an interface at a seam; it names a role, not substance.

**Leverage**: what callers get from depth: more capability per unit of interface, one implementation paying back across N call sites and M tests.

**Locality**: what maintainers get from depth: change, bugs, knowledge and verification concentrate in one place. Fix once, fixed everywhere.

## Principles

- **Depth is a property of the interface.** A deep module may be built from small, swappable parts; they are just not in its interface. It can have **internal seams** for its own tests besides the **external seam** at its interface.
- **The deletion test.** Imagine deleting the module. Complexity that vanishes was a pass-through; complexity that reappears across N callers was earning its keep.
- **The interface is the test surface.** Callers and tests cross the same seam; wanting to test past the interface means the module is the wrong shape.
- **One adapter means a hypothetical seam. Two adapters means a real one.** Add a seam only where something actually varies.
- **Shrink the interface**: fewer methods, simpler parameters, more hidden inside. Accept dependencies instead of creating them, and return results instead of producing side effects; both make the module testable through its interface.

## Rejected framings

- **Depth as implementation lines over interface lines** (Ousterhout): it rewards padding. Depth here is leverage.
- **"Interface" as the `interface` keyword or a class's public methods**: too narrow; it covers every fact a caller must know.
- **"Boundary"**: say **seam** or **interface**.

## Going deeper

- **Deepening a cluster given its dependencies**: [DEEPENING.md](DEEPENING.md) has the dependency categories, seam discipline and replace-don't-layer testing.
- **Exploring alternative interfaces**: [DESIGN-IT-TWICE.md](DESIGN-IT-TWICE.md) runs parallel sub-agents that design the interface in radically different ways, then compares them. Its briefs carry the dependency category from DEEPENING.md.

_Adapted from Matt Pocock's `codebase-design` skill; provenance and the upstream MIT notice are recorded in [LICENSE](LICENSE)._
