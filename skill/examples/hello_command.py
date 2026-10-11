"""First real plugin: rewrites `.hello <name>` outgoing messages.

Teaches: metadata as plain constants, registering the outgoing-message hook
in on_plugin_load, building a settings page, returning HookResult.

See: reference/plugin-class.md, reference/settings.md, reference/client-utils.md
"""

from typing import Any, List

from base_plugin import (  # pyright: ignore[reportMissingImports]
    BasePlugin,
    HookResult,
    HookStrategy,
)
from ui.settings import (  # pyright: ignore[reportMissingImports]
    Header,
    Input,
    Text,
)

__id__ = "hello_world"
__name__ = "Hello World"
__description__ = "Rewrites .hello commands into a friendly message"
__author__ = "Your Name"
__version__ = "1.0.0"
__icon__ = "exteraPlugins/1"
__app_version__ = ">=12.5.1"
__sdk_version__ = ">=1.4.4.3"

DEFAULT_TEMPLATE = "Hello, {name}!"


class HelloWorldPlugin(BasePlugin):
    def on_plugin_load(self):
        # Implementing on_send_message_hook alone is NOT enough —
        # you must register it here.
        self.add_on_send_message_hook()
        self.log("Hello World plugin loaded")

    def create_settings(self) -> List[Any]:
        return [
            Header(text="Hello World"),
            Input(
                key="template",
                text="Greeting template",
                default=DEFAULT_TEMPLATE,
                subtext="Use {name} where the name should appear.",
                icon="msg_edit",
            ),
            Text(
                text="Example",
                subtext=".hello Alice -> Hello, Alice!",
                icon="msg_info",
            ),
        ]

    def on_send_message_hook(self, account: int, params: Any) -> HookResult:
        # Some sends are media-only — always validate that message exists.
        if not isinstance(getattr(params, "message", None), str):
            return HookResult()

        raw_text = params.message.strip()
        if not raw_text.startswith(".hello"):
            return HookResult()

        # Split once so ".hello Alice Smith" keeps the full name.
        parts = raw_text.split(" ", 1)
        name = parts[1].strip() if len(parts) > 1 else ""

        if not name:
            params.message = "Usage: .hello <name>"
            return HookResult(strategy=HookStrategy.MODIFY, params=params)

        template = self.get_setting("template", DEFAULT_TEMPLATE)
        try:
            params.message = template.format(name=name)
        except Exception:
            # Fail softly on a broken template.
            params.message = (
                "Template must contain valid Python format placeholders, e.g. {name}."
            )

        return HookResult(strategy=HookStrategy.MODIFY, params=params)
