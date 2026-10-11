"""Custom settings row via SimpleSettingFactory + Java view.

Teaches: building a custom Android view in Python, binding it into a settings
row, handling clicks through BulletinHelper.

See: reference/settings.md, reference/ui-helpers.md
"""

from typing import Any, List

from android.view import Gravity  # pyright: ignore[reportMissingImports]
from android.widget import LinearLayout, TextView  # pyright: ignore[reportMissingImports]
from org.telegram.messenger import (  # pyright: ignore[reportMissingImports]
    AndroidUtilities,
)
from org.telegram.ui.Components import (  # pyright: ignore[reportMissingImports]
    LayoutHelper,
)
from ui.bulletin import BulletinHelper  # pyright: ignore[reportMissingImports]
from ui.settings import (  # pyright: ignore[reportMissingImports]
    Custom,
    Header,
    SimpleSettingFactory,
)

from base_plugin import BasePlugin  # pyright: ignore[reportMissingImports]


def create_view(context, list_view, current_account, class_guid, resources_provider):
    layout = LinearLayout(context)
    layout.setOrientation(LinearLayout.VERTICAL)
    layout.setGravity(Gravity.CENTER)
    layout.setPadding(
        AndroidUtilities.dp(20),
        AndroidUtilities.dp(20),
        AndroidUtilities.dp(20),
        AndroidUtilities.dp(20),
    )

    title = TextView(context)
    title.setText("Tap me")
    layout.addView(
        title,
        LayoutHelper.createLinear(
            LayoutHelper.WRAP_CONTENT, LayoutHelper.WRAP_CONTENT
        ),
    )
    return layout


def bind_view(view, item, divider, adapter, list_view):
    view.getChildAt(0).setText("Tap me")


def on_click(plugin, item, view):
    BulletinHelper.show_info(f"Hello from {plugin.getName()}!")


# Build the factory once at import time.
InteractiveRowFactory = SimpleSettingFactory(
    create_view,
    bind_view,
    is_clickable=True,
    on_click=on_click,
)


class CustomSettingPlugin(BasePlugin):
    def create_settings(self) -> List[Any]:
        return [
            Header(text="Custom Controls"),
            # Pass the Java factory instance into Custom(...).
            Custom(factory=InteractiveRowFactory.instance.java),
        ]
