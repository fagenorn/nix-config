# ADR-console-017 — A manager gone while its sprint has work is brought back

Context: a manager that stops later stayed gone until the owner noticed. Decision: while its sprint has work, a manager gone for two minutes is woken in place first, and after two failed wakes a successor takes over and reads `sprint recap`. Three bring-backs within an hour stop the tries and raise one inbox item. Rejected: "nothing relaunches automatically" for a started manager with work, and unbounded retries.
