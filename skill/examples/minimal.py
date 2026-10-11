"""Minimal exteraGram plugin skeleton.

Copy this as the starting point for any new plugin. Rename the class and
metadata, then add hooks/settings as needed.

See: SKILL.md, reference/plugin-class.md
"""

from base_plugin import BasePlugin  # pyright: ignore[reportMissingImports]

__id__ = "my_plugin"               # 2-32 chars: letters / digits / _ / -
__name__ = "My Plugin"             # required
__description__ = "One-line description."  # markdown rendered in UI
__author__ = "@yourUsername"
__version__ = "1.0.0"              # default "1.0" if omitted
__icon__ = "exteraPlugins/1"       # StickerPackShortName/index
__app_version__ = ">=12.5.1"       # supports >= <= == > <
__sdk_version__ = ">=1.4.4.3"


class MyPlugin(BasePlugin):
    def on_plugin_load(self):
        self.log("My plugin loaded")

    def on_plugin_unload(self):
        self.log("My plugin unloaded")
