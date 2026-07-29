from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_delete_signal_suppression_depth: ContextVar[int] = (
    ContextVar(
        "tipping_delete_signal_suppression_depth",
        default=0,
    )
)


def read_model_delete_signals_suppressed() -> bool:
    """
    Liefert True, wenn einzelne Read-Model-Löschsignale
    innerhalb einer kontrollierten Sammellöschung
    unterdrückt werden sollen.
    """

    return (
        _delete_signal_suppression_depth.get()
        > 0
    )


@contextmanager
def suppress_read_model_delete_signals(
) -> Iterator[None]:
    """
    Unterdrückt kontextlokal einzelne Löschsignale.

    ContextVar verhindert, dass parallele Requests oder
    Worker-Prozesse durch die Unterdrückung beeinflusst
    werden.
    """

    current_depth = (
        _delete_signal_suppression_depth.get()
    )

    token = (
        _delete_signal_suppression_depth.set(
            current_depth + 1
        )
    )

    try:
        yield

    finally:
        _delete_signal_suppression_depth.reset(
            token
        )
