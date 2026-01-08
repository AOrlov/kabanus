from typing import Callable, Optional, TypeVar

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


def retry_with_item(
    max_attempts: int,
    pick_item: Callable[[], Optional[ItemT]],
    run: Callable[[ItemT], ResultT],
    on_error: Callable[[ItemT, int, int, Exception], bool],
) -> Optional[ResultT]:
    """Retry running `run` with items from `pick_item`."""
    for attempt in range(1, max_attempts + 1):
        item = pick_item()
        if item is None:
            return None
        try:
            return run(item)
        except Exception as exc:
            if on_error(item, attempt, max_attempts, exc):
                continue
            raise
    return None
