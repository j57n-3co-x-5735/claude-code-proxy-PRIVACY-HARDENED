import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from typing import Optional, AsyncGenerator, Dict, Any
from openai import AsyncOpenAI, AsyncAzureOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai._exceptions import APIError, RateLimitError, AuthenticationError, BadRequestError
import httpx

logger = logging.getLogger(__name__)

_SENSITIVE_HEADER_KEYWORDS = ("authorization", "key", "token", "secret")
_audit_log_path: Optional[str] = None


def _redact_headers(headers) -> Dict[str, str]:
    result = {}
    for k, v in headers.items():
        if any(kw in k.lower() for kw in _SENSITIVE_HEADER_KEYWORDS):
            result[k] = "[REDACTED]"
        else:
            result[k] = v
    return result


# Audit hooks use synchronous file I/O within async wrappers. The audit log is a
# diagnostic tool, not a production feature. Do not enable NETWORK_AUDIT_LOG under
# concurrent load.
async def _log_network_request(request: httpx.Request):
    if not _audit_log_path:
        return
    entry = {
        "direction": "request",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": request.method,
        "url": str(request.url),
        "headers": _redact_headers(request.headers),
    }
    try:
        with open(_audit_log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write network audit log: {e}")


async def _log_network_response(response: httpx.Response):
    if not _audit_log_path:
        return
    entry = {
        "direction": "response",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status_code": response.status_code,
        "url": str(response.url),
        "headers": _redact_headers(response.headers),
    }
    try:
        with open(_audit_log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write network audit log: {e}")


async def _strip_fingerprints(request: httpx.Request):
    to_remove = [k for k in request.headers.keys() if k.lower().startswith("x-stainless")]
    for key in to_remove:
        del request.headers[key]
    if "user-agent" in request.headers:
        del request.headers["user-agent"]


class OpenAIClient:
    """Async OpenAI client with cancellation support."""

    def __init__(self, api_key: str, base_url: str, timeout: int = 90,
                 api_version: Optional[str] = None,
                 custom_headers: Optional[Dict[str, str]] = None,
                 max_retries: int = 0,
                 network_audit_log: str = ""):
        global _audit_log_path
        _audit_log_path = network_audit_log or None

        self.api_key = api_key
        self.base_url = base_url
        self.custom_headers = custom_headers or {}

        default_headers = {
            "Content-Type": "application/json",
        }

        all_headers = {**default_headers, **self.custom_headers}

        request_hooks = [_strip_fingerprints, _log_network_request]
        response_hooks = [_log_network_response]

        stripped_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            event_hooks={
                "request": request_hooks,
                "response": response_hooks,
            },
        )

        if api_version:
            self.client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version=api_version,
                timeout=timeout,
                default_headers=all_headers,
                http_client=stripped_http_client,
                max_retries=max_retries,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                default_headers=all_headers,
                http_client=stripped_http_client,
                max_retries=max_retries,
            )
        self.active_requests: Dict[str, asyncio.Event] = {}

    async def create_chat_completion(self, request: Dict[str, Any], request_id: Optional[str] = None) -> Dict[str, Any]:
        """Send chat completion to OpenAI API with cancellation support."""

        if request_id:
            cancel_event = asyncio.Event()
            self.active_requests[request_id] = cancel_event

        try:
            completion_task = asyncio.create_task(
                self.client.chat.completions.create(**request)
            )

            if request_id:
                cancel_task = asyncio.create_task(cancel_event.wait())
                done, pending = await asyncio.wait(
                    [completion_task, cancel_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                if cancel_task in done:
                    completion_task.cancel()
                    raise HTTPException(status_code=499, detail="Request cancelled by client")

                completion = await completion_task
            else:
                completion = await completion_task

            return completion.model_dump()

        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=self.classify_openai_error(str(e)))
        except RateLimitError as e:
            raise HTTPException(status_code=429, detail=self.classify_openai_error(str(e)))
        except BadRequestError as e:
            raise HTTPException(status_code=400, detail=self.classify_openai_error(str(e)))
        except APIError as e:
            status_code = getattr(e, 'status_code', 500)
            raise HTTPException(status_code=status_code, detail=self.classify_openai_error(str(e)))
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise HTTPException(status_code=500, detail=self.classify_openai_error(str(e)))

        finally:
            if request_id and request_id in self.active_requests:
                del self.active_requests[request_id]

    async def create_chat_completion_stream(self, request: Dict[str, Any], request_id: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Send streaming chat completion to OpenAI API with cancellation support."""

        if request_id:
            cancel_event = asyncio.Event()
            self.active_requests[request_id] = cancel_event

        try:
            request["stream"] = True
            if "stream_options" not in request:
                request["stream_options"] = {}
            request["stream_options"]["include_usage"] = True

            streaming_completion = await self.client.chat.completions.create(**request)

            async for chunk in streaming_completion:
                if request_id and request_id in self.active_requests:
                    if self.active_requests[request_id].is_set():
                        raise HTTPException(status_code=499, detail="Request cancelled by client")

                chunk_dict = chunk.model_dump()
                chunk_json = json.dumps(chunk_dict, ensure_ascii=False)
                yield f"data: {chunk_json}"

            yield "data: [DONE]"

        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=self.classify_openai_error(str(e)))
        except RateLimitError as e:
            raise HTTPException(status_code=429, detail=self.classify_openai_error(str(e)))
        except BadRequestError as e:
            raise HTTPException(status_code=400, detail=self.classify_openai_error(str(e)))
        except APIError as e:
            status_code = getattr(e, 'status_code', 500)
            raise HTTPException(status_code=status_code, detail=self.classify_openai_error(str(e)))
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise HTTPException(status_code=500, detail=self.classify_openai_error(str(e)))

        finally:
            if request_id and request_id in self.active_requests:
                del self.active_requests[request_id]

    def classify_openai_error(self, error_detail: Any) -> str:
        """Provide specific error guidance for common OpenAI API issues."""
        error_str = str(error_detail).lower()

        if "unsupported_country_region_territory" in error_str or "country, region, or territory not supported" in error_str:
            return "OpenAI API is not available in your region. Consider using a VPN or Azure OpenAI service."

        if "invalid_api_key" in error_str or "unauthorized" in error_str:
            return "Invalid API key. Please check your OPENAI_API_KEY configuration."

        if "rate_limit" in error_str or "quota" in error_str:
            return "Rate limit exceeded. Please wait and try again, or upgrade your API plan."

        if "model" in error_str and ("not found" in error_str or "does not exist" in error_str):
            return "Model not found. Please check your BIG_MODEL and SMALL_MODEL configuration."

        if "billing" in error_str or "payment" in error_str:
            return "Billing issue. Please check your OpenAI account billing status."

        return "Backend API error. Check proxy logs for details."

    def cancel_request(self, request_id: str) -> bool:
        """Cancel an active request by request_id."""
        if request_id in self.active_requests:
            self.active_requests[request_id].set()
            return True
        return False
