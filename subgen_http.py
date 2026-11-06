"""One retrying HTTP client for every paid provider call.

Before this module SubGen had four hand-written retry loops with different
rules: OpenAI audio uploads never retried (one 429 aborted a job), others
retried read timeouts up to six times with a 600 s timeout each (a single
transcription could run ~70 minutes and be billed up to seven times),
Retry-After was ignored, and a permanent OpenAI ``insufficient_quota`` 429
was retried as if it were transient.

Rules applied here:

* Retry 408/409/425/429/5xx/529 and connection failures with jittered
  exponential backoff, at most ``max_attempts`` attempts in total.
* Honour ``Retry-After`` / ``retry-after-ms`` and Gemini ``retryDelay``.
* Never retry a quota that cannot recover inside a retry loop (OpenAI
  ``insufficient_quota``, Gemini per-day RESOURCE_EXHAUSTED).
* Retry a *read timeout* at most ``max_timeout_retries`` times: the provider
  may already have done (and billed) the work.
"""

import email.utils
import http.client
import json
import random
import re
import socket
import time
import urllib.error
import urllib.request

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
DEFAULT_MAX_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 60.0


class ProviderHTTPError(RuntimeError):
    """A provider answered with a non-success status that was not retried."""

    def __init__(self, message, status=None, body=""):
        super().__init__(message)
        self.status = status
        self.body = body


def provider_retry_delay(error_body, fallback_delay):
    """Gemini puts the wait in error.details[].retryDelay ("12s")."""
    try:
        parsed = json.loads(error_body)
    except Exception:
        parsed = {}
    error = parsed.get("error") if isinstance(parsed, dict) else None
    for detail in (error or {}).get("details", []) if isinstance(error, dict) else []:
        retry_delay = detail.get("retryDelay") if isinstance(detail, dict) else None
        if isinstance(retry_delay, str):
            match = re.match(r"^(\d+(?:\.\d+)?)s$", retry_delay.strip())
            if match:
                return max(fallback_delay, float(match.group(1)) + random.uniform(0.25, 1.25))
    return fallback_delay


def provider_quota_is_non_retryable(error_body):
    """Quota exhaustion that cannot recover inside an HTTP retry loop."""
    try:
        parsed = json.loads(error_body)
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    error = parsed.get("error") or {}
    if not isinstance(error, dict):
        return False
    # OpenAI: billing quota exhausted (returned as 429).
    if str(error.get("code") or error.get("type") or "").lower() == "insufficient_quota":
        return True
    # Gemini: daily/project quota.
    if str(error.get("status") or "").upper() != "RESOURCE_EXHAUSTED":
        return False
    for detail in error.get("details") or []:
        for violation in (detail or {}).get("violations") or []:
            quota_id = str(violation.get("quotaId") or "").casefold()
            metric = str(violation.get("quotaMetric") or "").casefold()
            if "perday" in quota_id or "per_day" in quota_id or "requests_per_day" in metric:
                return True
    return "current quota" in str(error.get("message") or "").casefold() and "per day" in str(error)


def retry_after_seconds(headers):
    """Seconds requested by Retry-After (seconds or HTTP date) or retry-after-ms."""
    if not headers:
        return None
    milliseconds = headers.get("retry-after-ms")
    if milliseconds:
        try:
            return max(0.0, float(milliseconds) / 1000.0)
        except ValueError:
            pass
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())


def backoff_delay(attempt, base=2.0):
    return min(MAX_BACKOFF_SECONDS, base * (2 ** attempt) + random.uniform(0.1, 1.0))


def post_for_json(
    url,
    body,
    headers,
    *,
    timeout,
    label="Provider request",
    max_attempts=DEFAULT_MAX_ATTEMPTS,
    max_timeout_retries=1,
    sleep=time.sleep,
):
    """POST ``body`` (bytes) and return the decoded JSON response."""
    timeout_retries = 0
    for attempt in range(max_attempts):
        last_attempt = attempt == max_attempts - 1
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            quota_exhausted = provider_quota_is_non_retryable(error_body)
            if quota_exhausted:
                # subgen_longform matches this phrase to stop gap recovery early.
                raise ProviderHTTPError(
                    f"{label} failed with non-retryable daily quota: HTTP {exc.code}: {error_body}",
                    exc.code,
                    error_body,
                ) from exc
            retryable = exc.code in RETRYABLE_STATUS
            if retryable and not last_attempt:
                delay = retry_after_seconds(exc.headers)
                if delay is None:
                    delay = provider_retry_delay(error_body, backoff_delay(attempt))
                delay = min(delay, MAX_BACKOFF_SECONDS * 5)
                print(f"{label}: HTTP {exc.code}. Retrying in {delay:.1f}s (attempt {attempt + 2}/{max_attempts})...")
                sleep(delay)
                continue
            raise ProviderHTTPError(f"{label} failed: HTTP {exc.code}: {error_body}", exc.code, error_body) from exc
        except (TimeoutError, socket.timeout) as exc:
            # Read timeout: the request reached the provider and may be billed.
            if timeout_retries < max_timeout_retries and not last_attempt:
                timeout_retries += 1
                delay = backoff_delay(attempt)
                print(f"{label}: timed out after {timeout}s. Retrying once in {delay:.1f}s...")
                sleep(delay)
                continue
            raise RuntimeError(f"{label} failed: timed out after {timeout}s") from exc
        except (urllib.error.URLError, ConnectionError, http.client.HTTPException) as exc:
            # Connection refused/reset, DNS failure, or a dropped response.
            if not last_attempt:
                delay = backoff_delay(attempt)
                print(f"{label}: {exc}. Retrying in {delay:.1f}s (attempt {attempt + 2}/{max_attempts})...")
                sleep(delay)
                continue
            raise RuntimeError(f"{label} failed: {exc}") from exc
    raise RuntimeError(f"{label} failed after {max_attempts} attempts")  # pragma: no cover
