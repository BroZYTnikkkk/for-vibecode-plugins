# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""A pill in exteraGram's pill stack beside the chats' search (setting entry_pill, off by default): the song that
plays, a tap opens the player. The pill is the plugin's own Java class (sculpt.MusicPill, a BasePill), made by
exteraGram's PillRegistry through a creator from here; its words and its tap are set through static methods."""

from java import dynamic_proxy, jarray, jclass, jint

from .common import _ctx, _log, sculpt_class, sculpt_method

REGISTRY = "com.exteragram.messenger.pillstack.core.PillRegistry"
CONFIG = "com.exteragram.messenger.pillstack.core.PillStackConfig"
PILL_ID = 731001  # sculpt.MusicPill.ID
ICON_TOP, ICON_BOTTOM = -0x6F2E8B, -0x9E3A9A  # the icon's plate in the pill stack's settings, a warm pink

_kept = []  # the creator and its info: exteraGram holds them weakly enough that they must not be collected


def _class(name):
    return jclass("java.lang.Class").forName(name, False, _ctx().getClassLoader())


class _Run(dynamic_proxy(jclass("java.lang.Runnable"))):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def run(self):
        if self.action is not None:
            self.action()


def register(plugin, on_click):
    """Adds the pill to the registry and to the stack the user sees. False when this build has no pill stack."""
    pill_class = sculpt_class("sculpt.MusicPill")
    if pill_class is None:
        return False
    try:
        Registry = jclass(REGISTRY)
        Info = jclass(REGISTRY + "$PillInfo")
        Creator = jclass(REGISTRY + "$PillCreator")
    except Exception as e:
        _log("pill: no pill stack (%s)" % type(e).__name__)
        return False
    Object = jclass("java.lang.Object")
    maker = pill_class.getConstructor(jarray(jclass("java.lang.Class"))(
        [_class("android.content.Context"), _class("org.telegram.ui.ActionBar.Theme$ResourcesProvider")]))

    class Made(dynamic_proxy(Creator)):
        def create(self, context, provider):
            try:
                return maker.newInstance(jarray(Object)([context, provider]))
            except Exception as e:
                _log("pill: %s" % e)
                return None

    sculpt_method("sculpt.MusicPill", "setClick").invoke(None, _Run(on_click))
    creator = Made()
    icon = _ctx().getResources().getIdentifier("msg_played", "drawable", _ctx().getPackageName())
    info = Info(PILL_ID, "Sculpt Player", icon, ICON_TOP, ICON_BOTTOM, creator)
    _kept[:] = [creator, info]
    Registry.register(info)
    _show(True)
    return True


def unregister():
    try:
        jclass(REGISTRY).unregister(PILL_ID)
    except Exception:
        pass
    _show(False)
    release = sculpt_method("sculpt.MusicPill", "release")
    if release is not None:
        try:
            release.invoke(None)
        except Exception:
            pass
    _kept[:] = []


def _show(on):
    """In the stack the user sees, or out of it."""
    try:
        Config = jclass(CONFIG)
        active = Config.getActivePills()
        ids = [int(active.get(i)) for i in range(active.size())]
        if on and PILL_ID not in ids:
            active.add(jclass("java.lang.Integer")(PILL_ID))
        elif not on and PILL_ID in ids:
            active.remove(jclass("java.lang.Integer")(PILL_ID))  # the object, not the index
        else:
            return
        Config.savePillsLayout()
        Config.notifySettingsChanged(jarray(jint)([]))
    except Exception as e:
        _log("pill stack: %s" % e)


def set_text(text):
    method = sculpt_method("sculpt.MusicPill", "setText")
    if method is not None:
        try:
            method.invoke(None, text)
        except Exception:
            pass
