"""Metadados locais de duração; nunca registra pedidos, argumentos ou saídas.

Rotação de 3 x 2 MiB. Falha no diagnóstico nunca interrompe uma ação.
"""
import contextvars
import functools
import json
import inspect
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time
import uuid

_trace = contextvars.ContextVar('emily_trace', default='')
_lock = threading.Lock()
_logger = None


def event(kind, name, started, *, ok=True, error='', trace_id=None, **metrics):
    global _logger
    try:
        with _lock:
            if _logger is None:
                folder = Path(os.getenv('EMILY_DIAGNOSTICS_DIR', str(Path.home()/'.local/state/emily/diagnostics')))
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = folder/'performance.jsonl'
                handler = RotatingFileHandler(path, maxBytes=2*1024*1024, backupCount=2, encoding='utf-8')
                path.chmod(0o600)
                _logger = logging.Logger('emily-performance')
                _logger.addHandler(handler)
            row = dict(time=time.time(), trace=trace_id or _trace.get(), platform='pc', kind=kind,
                       name=str(name)[:100], ms=round((time.monotonic()-started)*1000, 2),
                       ok=ok, error=str(error)[:80])
            # Only numeric/boolean metrics; no user content or network URLs.
            row.update({k:v for k,v in metrics.items() if isinstance(v,(int,float,bool))})
            _logger.info(json.dumps(row, ensure_ascii=False))
    except Exception:
        pass


def measured(kind, name_arg=None):
    def decorate(fn):
        signature = inspect.signature(fn)
        @functools.wraps(fn)
        def call(*args, **kwargs):
            token = _trace.set(uuid.uuid4().hex[:16]) if not _trace.get() else None
            start = time.monotonic()
            name = signature.bind_partial(*args,**kwargs).arguments.get(name_arg,fn.__name__) if name_arg else fn.__name__
            try:
                value = fn(*args, **kwargs)
                ok = value.get('ok',True) if isinstance(value,dict) else getattr(value,'ok',True)
                error = value.get('erro','') if isinstance(value,dict) else getattr(value,'erro','')
                event(kind, name, start, ok=ok, error=error or '')
                return value
            except BaseException as exc:
                event(kind, name, start, ok=False, error=type(exc).__name__)
                raise
            finally:
                if token is not None: _trace.reset(token)
        return call
    return decorate


def stream_events(source, started, name):
    trace = _trace.get()
    def iterate():
        first = True
        ok = False
        try:
            for item in source:
                if first:
                    event('model_first_event',name,started,trace_id=trace)
                    first = False
                yield item
            ok = True
        except BaseException as exc:
            event('model_stream_error',name,started,ok=False,error=type(exc).__name__,trace_id=trace)
            raise
        finally:
            event('model_stream',name,started,ok=ok,trace_id=trace)
    return iterate()
