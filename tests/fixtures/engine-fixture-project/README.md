# Engine fixture project

A tiny Python project the engine's proof runs deliver against: one function in `fixture/greet.py` and one check in `checks/check_greet.py`. The tests build it in a temporary directory and adopt it with the adoption command, exactly as any project is adopted; the checks carry the `check_` prefix so no platform test scanner takes them for a suite member.
