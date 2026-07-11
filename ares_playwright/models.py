from dataclasses import dataclass
from enum import Enum


class AuthStatus(Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StateValidationResult:
    status: AuthStatus
    reason: str
    final_url: str = ""
    app_error: str = ""
