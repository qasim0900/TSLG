from typing import Any, Callable


def mounted_page(control: Any):
    try:
        return control.page
    except (RuntimeError, AttributeError):
        return None


def ui_callback(page, fn: Callable[..., Any]) -> Callable[..., None]:
    def schedule(*args: Any, **kwargs: Any) -> None:
        async def run_on_ui() -> None:
            fn(*args, **kwargs)

        page.run_task(run_on_ui)

    return schedule

