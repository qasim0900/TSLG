from flet.controls.base_control import BaseControl


def _short_control_repr(self) -> str:
    return BaseControl.__str__(self)


def install_cheap_control_repr() -> int:
    patched = 0
    pending = [BaseControl]
    while pending:
        cls = pending.pop()
        if cls.__dict__.get("__repr__") not in (None, _short_control_repr):
            setattr(cls, "__repr__", _short_control_repr)
            patched += 1
        pending.extend(cls.__subclasses__())
    return patched
