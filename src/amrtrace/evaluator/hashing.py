# canonical hashing so the same content always gives the same hash
import hashlib
import json


# sorted keys and fixed separators make the text form unique
def canonical_json(value) -> str:
    # NaN is refused on purpose, the adapter must send None instead
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_of(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
