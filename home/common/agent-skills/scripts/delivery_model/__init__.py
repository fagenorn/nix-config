"""Pure canonical delivery contracts, authority matching, and reduction."""
from ._canonical import (MODEL_INTERFACE_VERSION, DeliveryModelError,
    canonical_bytes, canonical_digest)
from ._objects import STAGE_ACTIONS, validate_custody_ref
from ._wire import validate_delivery_object
from ._reconcile import match_scope, reduce_delivery

__all__ = (
    "MODEL_INTERFACE_VERSION", "DeliveryModelError", "canonical_bytes",
    "canonical_digest", "validate_delivery_object", "validate_custody_ref",
    "match_scope", "reduce_delivery", "STAGE_ACTIONS",
)
