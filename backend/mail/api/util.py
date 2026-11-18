from __future__ import annotations

import functools
import json
import logging

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import JsonResponse

log = logging.getLogger("kern.mail.api")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.status = status
        self.code = code


def body(request) -> dict:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except ValueError:
        raise ApiError("Invalid JSON") from None
    if not isinstance(data, dict):
        raise ApiError("Expected a JSON object")
    return data


def api(methods: tuple[str, ...] = ("GET",)):
    """JSON view decorator: method check + uniform error responses."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return JsonResponse({"error": "method_not_allowed"}, status=405)
            try:
                result = fn(request, *args, **kwargs)
            except ApiError as exc:
                return JsonResponse({"error": exc.code, "detail": str(exc)}, status=exc.status)
            except ObjectDoesNotExist:
                return JsonResponse({"error": "not_found"}, status=404)
            except (ValueError, ValidationError) as exc:
                return JsonResponse({"error": "invalid", "detail": str(exc)[:500]}, status=400)
            if isinstance(result, dict) or isinstance(result, list):
                return JsonResponse(result, safe=False)
            return result

        return wrapper

    return deco


def iso(dt):
    return dt.isoformat() if dt else None


def int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
