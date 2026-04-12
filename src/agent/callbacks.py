"""LangChain callback handler for structured tool call logging."""
import time
from typing import Any, Union
from uuid import UUID

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src import metrics

log = structlog.get_logger()


class ToolLoggingCallback(BaseCallbackHandler):
    """Logs every tool call: name, input, output, duration."""

    def __init__(self, user_hash: str) -> None:
        super().__init__()
        self.user_hash = user_hash
        self._start_times: dict[str, float] = {}
        self._tool_names: dict[str, str] = {}

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "unknown")
        self._start_times[str(run_id)] = time.time()
        self._tool_names[str(run_id)] = tool_name
        log.info(
            "tool_call_start",
            tool=tool_name,
            input=input_str[:200],  # truncate long inputs
            user_hash=self.user_hash,
        )

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        key = str(run_id)
        elapsed = time.time() - self._start_times.pop(key, time.time())
        tool_name = self._tool_names.pop(key, "unknown")
        log.info(
            "tool_call_end",
            output_preview=str(output)[:100],
            elapsed_ms=int(elapsed * 1000),
            user_hash=self.user_hash,
        )
        metrics.tool_call_duration.labels(tool_name=tool_name).observe(elapsed)
        metrics.tool_calls_total.labels(tool_name=tool_name, status="success").inc()

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        key = str(run_id)
        elapsed = time.time() - self._start_times.pop(key, time.time())
        tool_name = self._tool_names.pop(key, "unknown")
        log.error(
            "tool_call_error",
            error=str(error),
            elapsed_ms=int(elapsed * 1000),
            user_hash=self.user_hash,
        )
        metrics.tool_calls_total.labels(tool_name=tool_name, status="error").inc()
        metrics.errors_total.labels(component="tool").inc()

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})
        input_tokens = usage.get("prompt_tokens") or 0
        output_tokens = usage.get("completion_tokens") or 0
        model = (response.llm_output or {}).get("model_name", "unknown")
        log.info(
            "llm_call_end",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            user_hash=self.user_hash,
        )
        if input_tokens:
            metrics.llm_tokens_total.labels(model=model, type="input").inc(input_tokens)
        if output_tokens:
            metrics.llm_tokens_total.labels(model=model, type="output").inc(output_tokens)
