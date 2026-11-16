# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""A tab of its own in the bottom bar of the chats screen (setting entry_main): a note and "Music", before the
profile tab; a tap opens the player. The tab is exteraGram's own kind (GlassTabView.createMainNavigationTab), so it
looks like its neighbors; it is added when MainTabsActivity builds its view or comes back, and never selected: the
player opens over the screen instead."""

import weakref

from android_utils import OnClickListener, run_on_ui_thread
from java import jclass

from .common import _ctx, _java_class, _log
from .i18n import tr

TAG = "sculpt_bottom_tab"
ACTIVITY = "org.telegram.ui.MainTabsActivity"
TAB = "org.telegram.ui.Components.glass.GlassTabView"
PROFILE = 4  # MainTabsActivity.tabs: the profile tab, the last one; ours goes before it

_state = {"activity": None, "tabs": [], "listeners": [], "hooked": False}


def _field(obj, name):
    cls = obj.getClass()
    while cls is not None:
        try:
            field = cls.getDeclaredField(name)
            field.setAccessible(True)
            return field.get(obj)
        except Exception:
            cls = cls.getSuperclass()
    return None


def _ours(tabs_view):
    for i in range(tabs_view.getChildCount()):
        child = tabs_view.getChildAt(i)
        if child is not None and child.getTag() == TAG:
            return child
    return None


def add(plugin, activity):
    """Our tab in this screen's bottom bar, once."""
    if activity is None or not plugin.get_setting("entry_main", True):
        return
    _state["activity"] = weakref.ref(activity)
    tabs_view = _field(activity, "tabsView")
    if tabs_view is None or _ours(tabs_view) is not None:
        return
    context = activity.getContext() or _ctx()
    Tab = jclass(TAB)
    animation = jclass(TAB + "$TabAnimation").SETTINGS
    title = context.getResources().getIdentifier("OK", "string", context.getPackageName())
    tab = Tab.createMainNavigationTab(context, activity.getResourceProvider(), animation, title)
    tab.setText(tr("Музыка"))
    icon = context.getResources().getIdentifier("msg_played", "drawable", context.getPackageName())
    image = _field(tab, "imageView")
    if image is not None and icon:
        image.setImageResource(icon)
        # without its animation the tab keeps the picture set here instead of the settings gear
        field = tab.getClass().getDeclaredField("tabAnimation")
        field.setAccessible(True)
        field.set(tab, None)
    tab.setTag(TAG)
    tab.setContentDescription("Sculpt Player")
    listener = OnClickListener(lambda view: run_on_ui_thread(plugin.open_from_menu))
    _state["listeners"].append(listener)
    tab.setOnClickListener(listener)
    native = _field(activity, "tabs")
    place = -1
    if native is not None and len(native) > PROFILE and native[PROFILE] is not None:
        place = tabs_view.indexOfChild(native[PROFILE])
    if place < 0:
        place = max(0, tabs_view.getChildCount() - 1)
    tabs_view.addView(tab, place)
    try:
        tabs_view.addTabToIgnoreClick(tab)
        tabs_view.setViewVisible(tab, True, False)
    except Exception:
        tab.setVisibility(0)
    _state["tabs"].append(tab)
    _log("bottom tab added")


def remove():
    for tab in _state["tabs"]:
        try:
            tab.setOnClickListener(None)
            parent = tab.getParent()
            if parent is not None:
                parent.removeView(tab)
        except Exception:
            pass
    _state["tabs"] = []
    _state["listeners"] = []


def refresh(plugin):
    """The switch changed, or the plugin started after the screen was built: the tab comes or goes now."""
    remove()
    ref = _state["activity"]
    activity = ref() if ref is not None else None
    if activity is None:
        activity = _find_activity()
    if activity is not None:
        try:
            add(plugin, activity)
        except Exception as e:
            _log("bottom tab: %s" % e)


def _find_activity():
    """The chats screen of the running app."""
    try:
        launch = jclass("org.telegram.ui.LaunchActivity").instance
        stack = launch.getActionBarLayout().getFragmentStack()
        wanted = _java_class(ACTIVITY)
        for i in range(stack.size()):
            fragment = stack.get(i)
            if wanted.isInstance(fragment):
                return fragment
    except Exception as e:
        _log("bottom tab: no chats screen (%s)" % type(e).__name__)
    return None


def install(plugin):
    """Hooks once per load; the tab itself follows the switch (refresh)."""
    if not _state["hooked"]:
        from .hooks import _Hook

        class Built(_Hook):
            """After MainTabsActivity.createView or onResume: the tab is put in (again)."""

            def after_hooked_method(self, param):
                try:
                    add(self.plugin, param.thisObject)
                except Exception as e:
                    _log("bottom tab: %s" % e)

        activity = _java_class(ACTIVITY)
        plugin.remember(plugin.hook_all_methods(activity, "createView", Built(plugin, "mainTabsCreateView")))
        plugin.remember(plugin.hook_all_methods(activity, "onResume", Built(plugin, "mainTabsResume")))
        _state["hooked"] = True
    run_on_ui_thread(lambda: refresh(plugin), 300)


def unload():
    remove()
    _state["hooked"] = False
    _state["activity"] = None
