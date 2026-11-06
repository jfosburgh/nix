"""Prompt/credential-free structured journal events and redacted stack traces."""
import json
import logging
import traceback

logger = logging.getLogger('narsil.inference')


def event(name, *, level=logging.INFO, **fields):
    # Callers pass only internal identifiers, counts, timings and telemetry.
    logger.log(level, json.dumps(dict(event=name, **fields), separators=(',', ':')))


def failure(name, error, **fields):
    # Exception messages/reprs may contain upstream bodies or request headers.
    # Preserve diagnostic stack locations and cause types, never values/locals.
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 5:
        seen.add(id(error))
        chain.append(dict(type=type(error).__name__, frames=[
            dict(file=f.filename, line=f.lineno, function=f.name)
            for f in traceback.extract_tb(error.__traceback__)]))
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    event(name, level=logging.ERROR, errors=chain, **fields)
