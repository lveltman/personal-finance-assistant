"""LangChain callback handler for structured tool call logging."""
import time
from typing import Any, Union
from uuid import UUID

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

log = structlog.get_logger()


class ToolLoggingCallback(BaseCallbackHandler):
    """Logs every tool call: name, input, output, duration."""

    def __init__(self, user_hash: str) -> None:
        super().__init__()
        self.user_hash = user_hash
        self._start_times: dict[str, float] = {}

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
        elapsed_ms = int((time.time() - self._start_times.pop(str(run_id), time.time())) * 1000)
        log.info(
            "tool_call_end",
            output_preview=str(output)[:100],
            elapsed_ms=elapsed_ms,
            user_hash=self.user_hash,
        )

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        elapsed_ms = int((time.time() - self._start_times.pop(str(run_id), time.time())) * 1000)
        log.error(
            "tool_call_error",
            error=str(error),
            elapsed_ms=elapsed_ms,
            user_hash=self.user_hash,
        )

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})
        log.info(
            "llm_call_end",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            user_hash=self.user_hash,
        )
