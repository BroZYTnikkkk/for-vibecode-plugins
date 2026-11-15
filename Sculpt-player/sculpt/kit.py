# Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).

"""Pieces the screens share so they look alike: a slider like exteraGram's own settings have, and a switch between
two or three parts drawn like Mornye's bottom bar. Colors come from the player (the cover's), through the screen."""

from java import dynamic_proxy, jclass

from .common import _dp, _log

_proxies = {}


def _proxy(name):
    """The listener classes are made when first needed: a missing Material slider must not break the import."""
    found = _proxies.get(name)
    if found is not None:
        return found
    if name == "change":
        class Changed(dynamic_proxy(jclass("com.google.android.material.slider.Slider$OnChangeListener"))):
            def __init__(self, action):
                super().__init__()
                self.action = action

            def onValueChange(self, slider, value, from_user, *more):
                if self.action is not None:
                    self.action(float(value))
        found = Changed
    elif name == "touch":
        class Touched(dynamic_proxy(jclass("com.google.android.material.slider.Slider$OnSliderTouchListener"))):
            def __init__(self, action):
                super().__init__()
                self.action = action

            def onStartTrackingTouch(self, slider, *more):
                pass

            def onStopTrackingTouch(self, slider, *more):
                if self.action is not None:
                    self.action(float(slider.getValue()))
        found = Touched
    else:
        class Seeked(dynamic_proxy(jclass("android.widget.SeekBar$OnSeekBarChangeListener"))):
            def __init__(self, changed, done):
                super().__init__()
                self.changed, self.done = changed, done

            def onProgressChanged(self, bar, progress, from_user, *more):
                if self.changed is not None:
                    self.changed(int(progress))

            def onStartTrackingTouch(self, bar, *more):
                pass

            def onStopTrackingTouch(self, bar, *more):
                if self.done is not None:
                    self.done(int(bar.getProgress()))
        found = Seeked
    _proxies[name] = found
    return found


def snap(value, low, high, step):
    value = max(low, min(high, value))
    return low + round((value - low) / step) * step


def slider_row(screen, container, title, low, high, step, value, label, done, live=None):
    """A title with the value on a small tonal plate, and a slider across the row.

    label(value) -> the plate's words; done(value) when the finger lets go; live(value) while it moves."""
    owner = screen.owner
    Params = jclass("android.widget.LinearLayout$LayoutParams")
    LinearLayout = jclass("android.widget.LinearLayout")
    column = LinearLayout(owner.context)
    column.setOrientation(1)
    column.setPadding(_dp(20), _dp(12), _dp(20), _dp(4))
    top = LinearLayout(owner.context)
    top.setOrientation(0)
    top.setGravity(16)
    name = screen.label(16, "text")
    name.setText(title)
    top.addView(name, Params(0, -2, 1.0))
    plate = screen.label(13, "onTonal", True)
    plate.setPadding(_dp(10), _dp(4), _dp(10), _dp(4))
    screen.back(plate, "tonal", _dp(8))
    top.addView(plate)
    column.addView(top, Params(-1, -2))
    value = snap(value, low, high, step)
    plate.setText(label(value))

    def moved(current):
        current = snap(current, low, high, step)
        plate.setText(label(current))
        if live is not None:
            screen.guarded(live, current)

    def stopped(current):
        screen.guarded(done, snap(current, low, high, step))

    slider = None
    try:
        Helper = jclass("com.exteragram.messenger.utils.ui.MaterialSliderUiHelper")
        slider = Helper.create(owner.context)
        Helper.applyContinuousStyle(slider)
        Helper.applyColors(slider, owner.color("accent"), _track(owner))
        slider.setValueFrom(float(low))
        slider.setValueTo(float(high))
        slider.setStepSize(float(step))
        Helper.setValue(slider, float(value))
        changed, touched = _proxy("change")(moved), _proxy("touch")(stopped)
        slider.addOnChangeListener(changed)
        slider.addOnSliderTouchListener(touched)
        screen.sliders.append((slider, (changed, touched), "material"))
    except Exception as e:
        _log("slider: material failed (%s), the system one" % type(e).__name__)
        slider = jclass("android.widget.SeekBar")(owner.context)
        count = int(round((high - low) / step))
        slider.setMax(count)
        slider.setProgress(int(round((value - low) / step)))
        tint = jclass("android.content.res.ColorStateList").valueOf(owner.color("accent"))
        slider.setProgressTintList(tint)
        slider.setThumbTintList(tint)
        listener = _proxy("seek")(lambda n: moved(low + n * step), lambda n: stopped(low + n * step))
        slider.setOnSeekBarChangeListener(listener)
        screen.sliders.append((slider, (listener,), "system"))
    column.addView(slider, Params(-1, _dp(44)))
    container.addView(column, Params(-1, -2))
    return slider


def _track(owner):
    try:
        return owner.color("track")
    except Exception:
        return jclass("androidx.core.graphics.ColorUtils").setAlphaComponent(owner.color("text"), 50)


def release_sliders(screen):
    for slider, listeners, kind in getattr(screen, "sliders", []):
        for listener in listeners:
            for attr in ("action", "changed", "done"):
                if hasattr(listener, attr):
                    setattr(listener, attr, None)
        try:
            if kind == "material":
                slider.clearOnChangeListeners()
                slider.clearOnSliderTouchListeners()
            else:
                slider.setOnSeekBarChangeListener(None)
        except Exception:
            pass
    screen.sliders = []


def segments(screen, items, selected, choose):
    """Two or three parts in one capsule with a thin outline, like Mornye's bottom bar: each an icon and its name in
    a line; the chosen one sits on a tonal pill that slides over to the part pressed.

    items: (icons, title). choose(index) when another one is pressed. Returns the row and a repaint(index)."""
    from android_utils import run_on_ui_thread
    owner = screen.owner
    Params = jclass("android.widget.LinearLayout$LayoutParams")
    FrameParams = jclass("android.widget.FrameLayout$LayoutParams")
    LinearLayout = jclass("android.widget.LinearLayout")
    ImageView = jclass("android.widget.ImageView")
    GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
    ColorUtils = jclass("androidx.core.graphics.ColorUtils")
    height = _dp(48)
    inner = _dp(4)
    outer = LinearLayout(owner.context)
    outer.setPadding(_dp(16), _dp(4), _dp(16), _dp(10))
    capsule = jclass("android.widget.FrameLayout")(owner.context)
    outline = GradientDrawable()
    outline.setCornerRadius(float(height / 2))
    capsule.setBackground(outline)
    capsule.setPadding(inner, inner, inner, inner)
    pill = jclass("android.view.View")(owner.context)
    capsule.addView(pill, FrameParams(0, height - 2 * inner))
    row = LinearLayout(owner.context)
    row.setOrientation(0)
    capsule.addView(row, FrameParams(-1, height - 2 * inner))
    outer.addView(capsule, Params(-1, height))
    parts = []
    for index, (icons, title) in enumerate(items):
        part = LinearLayout(owner.context)
        part.setOrientation(0)
        part.setGravity(17)
        icon = ImageView(owner.context)
        owner.set_icon(icon, icons)
        icon.setScaleType(jclass("android.widget.ImageView$ScaleType").FIT_CENTER)
        part.addView(icon, owner.params(20, 20))
        name = owner.text_view(14)
        name.setText(title)
        at = Params(-2, -2)
        at.setMarginStart(_dp(8))
        part.addView(name, at)
        part.setContentDescription(title)
        screen.click(part, choose, index)
        row.addView(part, Params(0, -1, 1.0))
        parts.append((icon, name))
    state = {"current": selected, "placed": False}

    def place(animate, tries=0):
        width = int(row.getWidth())
        if width <= 0:
            if tries < 20:
                run_on_ui_thread(lambda: place(False, tries + 1), 50)
            return
        share = width // max(1, len(parts))
        params = pill.getLayoutParams()
        if int(params.width) != share:
            params.width = share
            pill.setLayoutParams(params)
        target = float(share * state["current"])
        pill.animate().cancel()
        if animate and state["placed"]:
            pill.animate().translationX(target).setDuration(220).setInterpolator(
                jclass("android.view.animation.DecelerateInterpolator")()).start()
        else:
            pill.setTranslationX(target)
        state["placed"] = True

    def paint(current):
        moved = current != state["current"]
        state["current"] = current
        outline.setColor(0)
        outline.setStroke(max(1, _dp(1)), ColorUtils.setAlphaComponent(owner.color("textSecondary"), 110))
        pill.setBackground(owner.rounded(owner.color("tonal"), (height - 2 * inner) // 2))
        for index, (icon, name) in enumerate(parts):
            on = index == current
            owner.tint(icon, owner.color("onTonal") if on else owner.color("textSecondary"))
            name.setTextColor(owner.color("onTonal") if on else owner.color("textSecondary"))
            name.setTypeface(owner.bold if on else owner.regular)
            name.setSelected(on)
        place(moved)

    paint(selected)
    return outer, paint
