"""The one home of the phase-budget defaults (issue 424).

``workflow-state progress`` takes the argparse defaults of its turn and context
ceilings and headrooms from these constants; a caller that omits the flags gets
them, and a caller that passes a flag overrides its constant. The context meter
also reads them: it hands an owner off at ``CONTEXT_CEILING - CONTEXT_HEADROOM``.
"""

TURN_CEILING = 120
TURN_HEADROOM = 2
CONTEXT_CEILING = 120000
CONTEXT_HEADROOM = 10000
