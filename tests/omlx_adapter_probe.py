"""Exercise patched upstream code without loading MLX or its inference server.

The complete real endpoint is compiled from its AST, with network/GPU boundaries
supplied by this probe. Execution stops at engine preflight, after real request
parsing, conversion, template merging and budget resolution. The prompt renderer
uses the actual pinned Qwen template.
"""

import argparse
import ast
import asyncio
import inspect
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest

from jinja2 import Environment, TemplateError
from pydantic import ValidationError

from omlx.api.anthropic_models import MessagesRequest
from omlx.api.anthropic_utils import (
    convert_anthropic_to_internal, convert_anthropic_tools_to_internal,
)
from omlx.api.utils import (
    cache_reasoning_output, detect_and_strip_partial,
    merge_reasoning_effort_chat_template_kwargs, uses_native_reasoning_content,
)
from omlx.exceptions import InvalidRequestError
from omlx.model_settings import (
    ModelSettings, forced_ct_keys, merge_chat_template_request_kwargs,
)


class CapturedPreflight(Exception):
    def __init__(self, kwargs):
        self.kwargs = kwargs


class Lease:
    async def release(self):
        pass


async def nothing(*args, **kwargs):
    pass


class AdapterRouteTest(unittest.TestCase):
    def setUp(self):
        self.settings = ModelSettings(**MODEL_SETTINGS)
        self.entry = SimpleNamespace(
            config_model_type="qwen4_exp",
            reasoning_efforts=["low", "medium", "xhigh"],
            preserve_thinking_default=True,
        )
        self.prompt = None
        self.engine = SimpleNamespace(
            model_type="qwen4_exp", tokenizer=None, preflight_chat=self.capture,
        )
        self.namespace = {
            "__name__": "omlx_adapter_route_probe", "inspect": inspect,
            "logger": logging.getLogger(__name__),
            "InvalidRequestError": InvalidRequestError,
            "HTTPException": RuntimeError,
            "merge_reasoning_effort_chat_template_kwargs": merge_reasoning_effort_chat_template_kwargs,
            "merge_chat_template_request_kwargs": merge_chat_template_request_kwargs,
            "forced_ct_keys": forced_ct_keys,
            "MINIMAX_M3_MODEL_TYPES": frozenset({"minimax_m3", "minimax_m3_vl"}),
            "_AUTO_MODE_CLASSIFIER_THINKING_BUDGET": 256,
            "_server_state": SimpleNamespace(oq_manager=None, mcp_manager=None),
            "_LLMEngineLease": Lease,
            "_reject_lone_surrogates": lambda request: None,
            "get_engine_for_model": self.get_engine,
            "_serving_model_id": lambda lease, model: model,
            "get_engine_pool": lambda: SimpleNamespace(get_entry=lambda model: self.entry),
            "get_model_settings_for_request": lambda model: self.settings,
            "_engine_accepts_images": lambda engine: False,
            "uses_native_reasoning_content": uses_native_reasoning_content,
            "convert_anthropic_to_internal": convert_anthropic_to_internal,
            "convert_anthropic_tools_to_internal": convert_anthropic_tools_to_internal,
            "detect_and_strip_partial": detect_and_strip_partial,
            "get_sampling_params": lambda *args, **kwargs: (1., 1., 0, 1., 0., 0., 0., 8192, 0., 0.),
            "is_auto_mode_classifier_request": lambda request: False,
            "cache_reasoning_output": cache_reasoning_output,
            "_ensure_tokenizer_for_system_probe": nothing,
            "prepare_system_messages_for_template": lambda messages, *args, **kwargs: messages,
            "_unsupported_mid_system_policy": lambda: "preserve",
            "_prepare_chat_prompt_for_request": self.render,
            "validate_context_window": lambda *args: None,
            "_raise_if_llm_lease_abort_requested": nothing,
        }
        # Execute the actual endpoint, not a copied approximation of its merge.
        tree = ast.parse(SERVER_SOURCE.read_text())
        names = {"_merge_anthropic_chat_template_kwargs", "_resolve_thinking_budget", "create_anthropic_message",
                 "_cache_store_kwargs"}
        constants = {"_CACHE_STORE_HEADER"}
        nodes = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)]
        functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        nodes += functions
        for node in functions:
            node.decorator_list = []
            node.args.defaults = []
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(SERVER_SOURCE), "exec"), self.namespace)

    async def get_engine(self, *args, **kwargs):
        return self.engine

    async def capture(self, messages, **kwargs):
        raise CapturedPreflight(kwargs)

    def render(self, engine, messages, tools, *, chat_template_kwargs, is_partial):
        def reject(message):
            raise TemplateError(message)
        template = Environment().from_string(TEMPLATE.read_text())
        self.prompt = template.render(
            messages=messages, tools=tools, add_generation_prompt=True,
            raise_exception=reject, **(chat_template_kwargs or {}),
        )
        return 100, self.prompt

    def route(self, **kwargs):
        request = MessagesRequest.model_validate({
            "model": "qwen3.8-flash-next", "max_tokens": 8192,
            "messages": [{"role": "user", "content": "Say hello."}],
            "stream": True, **kwargs,
        })
        with self.assertRaises(CapturedPreflight) as caught:
            asyncio.run(self.namespace["create_anthropic_message"](
                request, SimpleNamespace(headers={}), None,
            ))
        return caught.exception.kwargs

    def test_all_claude_efforts_reach_real_template(self):
        for effort, expected in (("low", "low"), ("medium", "medium"), ("high", "xhigh"), ("xhigh", "xhigh"), ("max", "xhigh")):
            with self.subTest(effort=effort):
                result = self.route(output_config={"effort": effort}, thinking={"type": "adaptive"})
                self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], expected)
                self.assertTrue(result["chat_template_kwargs"]["enable_thinking"])
                self.assertEqual(result["thinking_budget"], 4096)
                self.assertEqual("Keep your thinking brief" in self.prompt, expected == "low")
                self.assertEqual("Please think carefully" in self.prompt, expected == "xhigh")

    def test_unsupported_api_efforts_fail_parsing(self):
        for effort in ("ultra", "", "LOW", 7, True):
            with self.subTest(effort=effort), self.assertRaises(ValidationError):
                self.route(output_config={"effort": effort})

    def test_default_medium_and_no_output_config_preserve_budget(self):
        for config in ({}, {"output_config": {}}, {"output_config": {"effort": None}}, {"output_config": {"format": {"type": "json_schema"}}}):
            with self.subTest(config=config):
                result = self.route(**config)
                self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], "medium")
                self.assertEqual(result["thinking_budget"], 4096)

    def test_explicit_template_effort_wins_and_other_values_survive(self):
        result = self.route(output_config={"effort": "max"}, chat_template_kwargs={"reasoning_effort": "low", "custom_key": 42})
        self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], "low")
        self.assertEqual(result["chat_template_kwargs"]["custom_key"], 42)

    def test_invalid_explicit_template_effort_fails_before_renderer_fallback(self):
        for effort in ("high", "invalid", None, [], {}):
            with self.subTest(effort=effort), self.assertRaises(InvalidRequestError):
                self.route(chat_template_kwargs={"reasoning_effort": effort})

    def test_thinking_enable_adaptive_disable_and_explicit_budget(self):
        for mode in ("enabled", "adaptive", "disabled"):
            with self.subTest(mode=mode):
                result = self.route(output_config={"effort": "low"}, thinking={"type": mode, "budget_tokens": 2048})
                self.assertEqual(result["chat_template_kwargs"]["enable_thinking"], mode != "disabled")
                self.assertEqual(result["thinking_budget"], 2048)
                if mode == "disabled":
                    self.assertNotIn("Keep your thinking brief", self.prompt)

    def test_disabled_template_is_not_reenabled_by_default_budget(self):
        result = self.route(chat_template_kwargs={"enable_thinking": False})
        self.assertFalse(result["chat_template_kwargs"]["enable_thinking"])

    def test_forced_model_settings_win(self):
        self.settings.chat_template_kwargs = {"reasoning_effort": "medium", "enable_thinking": False}
        self.settings.forced_ct_kwargs = ["reasoning_effort", "enable_thinking"]
        result = self.route(output_config={"effort": "high"}, chat_template_kwargs={"reasoning_effort": "low"}, thinking={"type": "enabled"})
        self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], "medium")
        self.assertFalse(result["chat_template_kwargs"]["enable_thinking"])

    def test_other_templates_keep_their_high_effort(self):
        self.entry.config_model_type = "glm5_next"
        result = self.route(output_config={"effort": "high"}, thinking={"type": "disabled"})
        self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], "high")

    def test_qwen_template_with_high_alias_keeps_it_and_maps_max(self):
        # Splash's generated Qwen template advertises high as an xhigh alias.
        self.entry.reasoning_efforts = ["low", "medium", "high", "xhigh"]
        result = self.route(output_config={"effort": "max"})
        self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], "xhigh")
        result = self.route(output_config={"effort": "low"}, chat_template_kwargs={"reasoning_effort": "high"}, thinking={"type": "disabled"})
        self.assertEqual(result["chat_template_kwargs"]["reasoning_effort"], "high")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-source", type=Path, required=True)
    parser.add_argument("--model-settings", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()
    SERVER_SOURCE = args.server_source
    TEMPLATE = args.template
    MODEL_SETTINGS = json.loads(args.model_settings.read_text())["models"]["Qwen3.8-Flash-Next-oQ4e-mtp"]
    unittest.main(argv=[__file__], verbosity=2)
