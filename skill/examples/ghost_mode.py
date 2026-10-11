"""Ghost Mode: block typing/offline requests via pre_request_hook.

Teaches: registering hooks by request name, HookStrategy.CANCEL and MODIFY,
post_request_hook for observing responses, building a settings page.

See: reference/plugin-class.md, reference/settings.md
"""

from typing import Any, List

from base_plugin import (  # pyright: ignore[reportMissingImports]
    BasePlugin,
    HookResult,
    HookStrategy,
)
from ui.settings import Switch  # pyright: ignore[reportMissingImports]

__id__ = "ghost_mode"
__name__ = "Ghost Mode"
__description__ = "Hide typing and online status"
__author__ = "Your Name"
__version__ = "1.0.0"
__icon__ = "exteraPlugins/1"
__app_version__ = ">=12.5.1"
__sdk_version__ = ">=1.4.4.3"

TYPING_REQUESTS = ["TL_messages_setTyping", "TL_messages_setEncryptedTyping"]


class GhostModePlugin(BasePlugin):
    def on_plugin_load(self):
        for req_name in TYPING_REQUESTS:
            self.add_hook(req_name)
        self.add_hook("TL_account_updateStatus")

    def pre_request_hook(
        self, request_name: str, account: int, request: Any
    ) -> HookResult:
        if (
            request_name in TYPING_REQUESTS
            and self.get_setting("dont_send_typing", True)
        ):
            self.log(f"Blocking request: {request_name}")
            return HookResult(strategy=HookStrategy.CANCEL)

        if (
            request_name == "TL_account_updateStatus"
            and self.get_setting("force_offline", True)
        ):
            request.offline = True
            return HookResult(strategy=HookStrategy.MODIFY, request=request)

        return HookResult()

    def post_request_hook(
        self,
        request_name: str,
        account: int,
        response: Any,
        error: Any,
    ) -> HookResult:
        if request_name == "TL_messages_sendMessage" and not error:
            self.log("Successfully sent a message!")
        return HookResult()

    def create_settings(self) -> List[Any]:
        return [
            Switch(
                key="dont_send_typing",
                text="Don't send typing status",
                default=True,
            ),
            Switch(
                key="force_offline",
                text="Always appear offline",
                default=True,
            ),
        ]
