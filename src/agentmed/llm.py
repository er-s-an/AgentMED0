from __future__ import annotations

from typing import Any, Callable

from openai import OpenAI

from agentmed.config import Settings
from agentmed.observability import Observability


class LLM:
    def __init__(self, settings: Settings, obs: Observability) -> None:
        self.settings = settings
        self.obs = obs
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    def complete(
        self,
        *,
        role: str,
        system: str,
        user: str,
        tools: list[dict[str, Any]] | None = None,
        tool_handler: Callable[[str, dict[str, Any]], str] | None = None,
        max_turns: int = 8,
    ) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for _ in range(max_turns):
            kwargs: dict[str, Any] = {
                "model": self.settings.agentmed_model,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
            response = self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message
            tool_calls = message.tool_calls or []
            content = message.content or ""
            self.obs.generation(
                name=f"{role}.llm",
                model=self.settings.agentmed_model,
                input_text=user if len(messages) == 2 else content,
                output_text=content or str([call.function.name for call in tool_calls]),
                usage={
                    "input": getattr(response.usage, "prompt_tokens", None),
                    "output": getattr(response.usage, "completion_tokens", None),
                },
            )
            if not tool_calls:
                return content
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.function.name, "arguments": call.function.arguments},
                        }
                        for call in tool_calls
                    ],
                }
            )
            import json

            for call in tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = tool_handler(call.function.name, args) if tool_handler else "no handler"
                messages.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})
        return "INCONCLUSIVE: max tool turns reached"
