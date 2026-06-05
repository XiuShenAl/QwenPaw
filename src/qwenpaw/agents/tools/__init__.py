# -*- coding: utf-8 -*-
# Note: ``execute_python_code`` / ``view_text_file`` / ``write_text_file``
# are intentionally not re-exported — qwenpaw's react_agent does not
# register them. The literal names still appear in
# ``security/tool_guard`` guardians for backward compatibility with
# pre-existing allowlists.
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Callable

from .file_io import (
    read_file,
    write_file,
    edit_file,
    append_file,
)
from .file_search import (
    grep_search,
    glob_search,
)
from .shell import execute_shell_command
from .send_file import send_file_to_user
from .browser_control import browser_use
from .desktop_screenshot import desktop_screenshot
from .view_media import view_image, view_video
from .get_current_time import get_current_time, set_user_timezone
from .get_token_usage import get_token_usage
from .agent_management import (
    list_agents,
    chat_with_agent,
    submit_to_agent,
    check_agent_task,
)
from .delegate_external_agent import delegate_external_agent

# Registered via react_agent's hardcoded tool_functions; kept out of
# __all__ so it's always enabled, not gated on agent config.
from .make_skill_tools import materialize_skill  # noqa: F401

__all__ = [
    "execute_shell_command",
    "read_file",
    "write_file",
    "edit_file",
    "append_file",
    "grep_search",
    "glob_search",
    "send_file_to_user",
    "desktop_screenshot",
    "view_image",
    "view_video",
    "browser_use",
    "get_current_time",
    "set_user_timezone",
    "get_token_usage",
    "delegate_external_agent",
    "list_agents",
    "chat_with_agent",
    "submit_to_agent",
    "check_agent_task",
    "discover_builtin_tool_funcs",
]


def discover_builtin_tool_funcs() -> list[Callable]:
    """Walk this subpackage and return all functions carrying a
    ``_tool_descriptor`` attribute (produced by ``@tool_descriptor``).

    Modules starting with ``_`` are skipped — they're private helpers
    (``_lsp_client``, ``_lsp_servers``) that shouldn't be auto-loaded
    just to scan for tools.
    """
    funcs: list[Callable] = []
    seen: set[int] = set()
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        for _, obj in inspect.getmembers(mod):
            if callable(obj) and hasattr(obj, "_tool_descriptor"):
                if id(obj) in seen:
                    continue
                seen.add(id(obj))
                funcs.append(obj)
    return funcs
