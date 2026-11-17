"""Error text for HTTP responses that never carries exception details.

An exception's message can hold file paths, SQL, hostnames, library
internals or, from some client libraries, the request that failed with its
credentials. Responses used to return ``str(exc)`` (and in places
``traceback.format_exc()``) to the browser. They now return a fixed message
with a short reference, and the exception goes to the server log under the
same reference so an administrator can find it.

    except Exception as exc:
        return JsonResponse({'error': public_error(exc, 'Export failed')}, status=500)
"""
import logging
import uuid

logger = logging.getLogger('clientst0r.errors')


def public_error(exc, summary='The request failed', *, log=None):
    """Log ``exc`` with its traceback and return a message safe to show.

    ``summary`` is a fixed, human-written phrase (never built from the
    exception). The returned text is ``"<summary>. See the server log
    (reference <ref>)."``.
    """
    ref = uuid.uuid4().hex[:8]
    (log or logger).error('%s [ref %s]', summary, ref, exc_info=(type(exc), exc, exc.__traceback__)
                          if isinstance(exc, BaseException) else None)
    summary = (summary or 'The request failed').rstrip('. ')
    return f'{summary}. See the server log (reference {ref}).'
