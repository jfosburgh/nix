"""Non-loading input accounting contract, independent of scheduler and HTTP.

Counters must cover the COMPLETE effective prompt: templates, stored system text,
tools/schema, special tokens, prior token context and any supported modalities.
There is deliberately no characters-per-token or generic byte-count fallback.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Protocol


class BudgetError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


class UnsupportedInput(Exception):
    """Counter cannot account for this envelope/modality without inference."""


@dataclass(frozen=True)
class BudgetRequest:
    model: str
    path: str
    body: bytes = field(repr=False)
    context: int
    output: int
    sequences: int


@dataclass(frozen=True)
class InputUsage:
    model: str
    context: int  # Actual, verified effective backend context; not just requested size.
    tokens: tuple[int, ...]  # One full prompt count per independently inferred input.


class InputCounter(Protocol):
    async def count(self, request: BudgetRequest) -> InputUsage:
        """Exact or proven upper-bound counts; never loads a model or allocates GPU.

        Raise UnsupportedInput for unhandled fields/templates/modalities. Unknown
        backend defaults, templates or tokenizer versions must fail, not estimate.
        """
        ...


async def check_budget(counter: InputCounter | None, request: BudgetRequest, *, timeout: float) -> None:
    if (type(request.context) is not int or request.context <= 0
            or type(request.output) is not int or request.output < 0
            or type(request.sequences) is not int or request.sequences < 0 or timeout <= 0):
        raise ValueError('Invalid budget request/timeout')
    if counter is None:
        raise BudgetError(503, 'Verified non-loading input accounting is not configured')
    try:
        async with asyncio.timeout(timeout):
            usage = await counter.count(request)
    except UnsupportedInput:
        raise BudgetError(422, 'Input shape or modality cannot be safely accounted for') from None
    except Exception:
        # Do not leak prompts, paths, tokenizer errors or backend credentials.
        # CancelledError is a BaseException and must propagate on disconnect.
        raise BudgetError(503, 'Verified input accounting unavailable') from None
    if (not isinstance(usage, InputUsage) or usage.model != request.model
            or type(usage.context) is not int or usage.context != request.context
            or not isinstance(usage.tokens, tuple) or len(usage.tokens) != request.sequences
            or any(type(value) is not int or value < 0 for value in usage.tokens)):
        raise BudgetError(503, 'Input accounting does not match the configured request/profile')
    if any(value + request.output > request.context for value in usage.tokens):
        raise BudgetError(422, 'Input plus output budget exceeds model context; request was not truncated')
