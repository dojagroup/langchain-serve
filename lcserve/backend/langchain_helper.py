import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import WebSocket
from langchain.callbacks import OpenAICallbackHandler
from langchain.callbacks.base import BaseCallbackHandler
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.schema import AgentAction, LLMResult
from opentelemetry.trace import Span, Tracer, set_span_in_context
from pydantic import BaseModel, ValidationError


def get_tracing_logger():
    logger = logging.getLogger("tracing")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Check if the logger already has handlers
    if not logger.handlers:
        formatter = logging.Formatter("%(name)s: %(message)s")
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


_span_map = {}


@dataclass
class TraceInfo:
    trace: str
    span: str
    action: str
    prompts: Optional[List[str]] = None
    outputs: str = ""
    tokens: Optional[int] = None
    cost: Optional[float] = None


class TracingCallbackHandlerMixin(BaseCallbackHandler):
    def __init__(self, tracer: Tracer, parent_span: Span):
        super().__init__()
        self.tracer = tracer
        self.parent_span = parent_span
        self.logger = get_tracing_logger()
        self.total_tokens = 0
        self.total_cost = 0

    def _register_span(self, run_id, span):
        _span_map[run_id] = span

    def _current_span(self, run_id):
        return _span_map.get(run_id)

    def _end_span(self, run_id):
        span = _span_map.pop(run_id, None)
        if span:
            span.end()

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        if not self.tracer:
            return

        operation = "langchain.llm"

        try:
            context = set_span_in_context(self.parent_span)
            with self.tracer.start_as_current_span(
                "llm", context=context, end_on_exit=False
            ) as span:
                span.set_attribute("otel.operation.name", operation)
                prompts_len = sum([len(prompt) for prompt in prompts])
                span.set_attribute("num_processed_prompts", len(prompts))
                span.set_attribute("prompts_len", prompts_len)
                span.add_event("prompts", {"data": prompts})
                span_context = span.get_span_context()

                trace_info = TraceInfo(
                    trace=span_context.trace_id,
                    span=span_context.span_id,
                    action="on_llm_start",
                    prompts=prompts,
                )
                self.logger.info(json.dumps(trace_info.__dict__))
                self._register_span(run_id, span)
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        if not self.tracer:
            return

        try:
            span = self._current_span(run_id)
            token_usage = response.llm_output["token_usage"]

            for k, v in token_usage.items():
                span.set_attribute(k, v)

            texts = "\n".join(
                [" ".join([l.text for l in lst]) for lst in response.generations]
            )
            span_context = span.get_span_context()
            trace_info = TraceInfo(
                trace=span_context.trace_id,
                span=span_context.span_id,
                action="on_llm_end",
                outputs=texts,
                tokens=round(self.total_tokens, 3) if self.total_tokens else None,
                cost=round(self.total_cost, 3) if self.total_cost else None,
            )
            self.logger.info(json.dumps(trace_info.__dict__))
            span.add_event("outputs", {"data": texts})
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)
        finally:
            self._end_span(run_id)

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        if not self.tracer:
            return

        operation = "langchain.chain"

        try:
            context = set_span_in_context(self.parent_span)
            with self.tracer.start_as_current_span(
                "chain", context=context, end_on_exit=False
            ) as span:
                span.set_attribute("otel.operation.name", operation)
                span.add_event("inputs", {"data": json.dumps(inputs)})
                self._register_span(run_id, span)
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        if not self.tracer:
            return

        try:
            span = self._current_span(run_id)
            span.add_event("outputs", {"data": json.dumps(outputs)})
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)
        finally:
            self._end_span(run_id)

    def on_agent_action(
        self,
        action: AgentAction,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        if not self.tracer:
            return

        try:
            span = self._current_span(run_id)
            span.add_event(
                "agent_action",
                {
                    "data": action.tool,
                    "tool_input": action.tool_input,
                    "log": action.log,
                },
            )
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        if not self.tracer:
            return

        operation = "langchain.tools"

        try:
            context = set_span_in_context(self.parent_span)
            with self.tracer.start_as_current_span(
                "tool", context=context, end_on_exit=False
            ) as span:
                span.set_attribute("otel.operation.name", operation)
                span.add_event("input", {"data": input_str})
                self._register_span(run_id, span)
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)

    def on_tool_end(self, output: str, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            span = self._current_span(run_id)
            span.add_event("output", {"data": output})
        except Exception:
            self.logger.error("Error in tracing callback handler", exc_info=True)
        finally:
            self._end_span(run_id)


class TracingCallbackHandler(TracingCallbackHandlerMixin):
    pass


class OpenAITracingCallbackHandler(TracingCallbackHandlerMixin, OpenAICallbackHandler):
    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        # Set the computed total token used and total cost first with OpenAICallbackHandler and then handle the tracing
        OpenAICallbackHandler.on_llm_end(self, response, run_id=run_id, **kwargs)
        TracingCallbackHandlerMixin.on_llm_end(self, response, run_id=run_id, **kwargs)


class AsyncStreamingWebsocketCallbackHandler(StreamingStdOutCallbackHandler):
    def __init__(self, websocket: "WebSocket", output_model: "BaseModel"):
        super().__init__()
        self.websocket = websocket
        self.output_model = output_model

    @property
    def always_verbose(self) -> bool:
        return True

    @property
    def is_async(self) -> bool:
        return True

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        try:
            data = self.output_model(result=token, error="").dict()
        except ValidationError:
            data = {"result": token, "error": ""}
        await self.websocket.send_json(data)

    async def on_text(self, text: str, **kwargs: Any) -> None:
        try:
            data = self.output_model(result=text, error="").dict()
        except ValidationError:
            data = {"result": text, "error": ""}
        await self.websocket.send_json(data)


class AsyncTracingCallbackHandler(TracingCallbackHandler):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        super().on_llm_start(
            serialized, prompts, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    async def on_llm_end(
        self, response: LLMResult, *, run_id: UUID, **kwargs: Any
    ) -> None:
        super().on_llm_end(response, run_id=run_id, **kwargs)

    async def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        super().on_chain_start(
            serialized, inputs, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    async def on_chain_end(
        self, outputs: Dict[str, Any], *, run_id: UUID, **kwargs: Any
    ) -> None:
        super().on_chain_end(outputs, run_id=run_id, **kwargs)

    async def on_agent_action(
        self,
        action: AgentAction,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        super().on_agent_action(
            action, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> None:
        super().on_tool_start(
            serialized, input_str, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )

    async def on_tool_end(self, output: str, *, run_id: UUID, **kwargs: Any) -> None:
        super().on_tool_end(output, run_id=run_id, **kwargs)


class StreamingWebsocketCallbackHandler(AsyncStreamingWebsocketCallbackHandler):
    @property
    def is_async(self) -> bool:
        return False

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        asyncio.run(super().on_llm_new_token(token, **kwargs))

    def on_text(self, text: str, **kwargs: Any) -> None:
        asyncio.run(super().on_text(text, **kwargs))


class _HumanInput(BaseModel):
    prompt: str


class InputWrapper:
    """Wrapper for human input."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        websocket: "WebSocket",
        recv_lock: asyncio.Lock,
    ):
        self.loop = loop
        self.websocket = websocket
        self.recv_lock = recv_lock

    async def __acall__(self, __prompt: str = ""):
        _human_input = _HumanInput(prompt=__prompt)
        async with self.recv_lock:
            await self.websocket.send_json(_human_input.dict())
        return await self.websocket.receive_text()

    def __call__(self, __prompt: str = ""):
        return asyncio.run_coroutine_threadsafe(
            self.__acall__(__prompt), self.loop
        ).result()


class PrintWrapper:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        websocket: "WebSocket",
        output_model: "BaseModel",
    ):
        self.loop = loop
        self.websocket = websocket
        self.output_model = output_model

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        asyncio.run_coroutine_threadsafe(self.__acall__(*args, **kwds), self.loop)

    async def __acall__(self, *args: Any, **kwds: Any) -> Any:
        await self.websocket.send_json(
            self.output_model(result="", error="", stdout=" ".join(args)).dict()
        )


class BuiltinsWrapper:
    """Context manager to wrap builtins with websocket."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        websocket: "WebSocket",
        output_model: "BaseModel",
        wrap_print: bool = True,
        wrap_input: bool = True,
    ):
        self.loop = loop
        self.websocket = websocket
        self.output_model = output_model
        self._wrap_print = wrap_print
        self._wrap_input = wrap_input

    def __enter__(self):
        import builtins

        if self._wrap_print:
            self._print = builtins.print
            builtins.print = PrintWrapper(self.loop, self.websocket, self.output_model)

        if self._wrap_input:
            self._input = builtins.input
            builtins.input = InputWrapper(self.loop, self.websocket, asyncio.Lock())

    def __exit__(self, exc_type, exc_val, exc_tb):
        import builtins

        if self._wrap_print:
            builtins.print = self._print

        if self._wrap_input:
            builtins.input = self._input