_approval_required = False


def set_approval_required(value: bool) -> None:
    global _approval_required
    _approval_required = bool(value)


def is_approval_required() -> bool:
    return _approval_required
