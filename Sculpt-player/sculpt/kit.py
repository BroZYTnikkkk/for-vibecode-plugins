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
    """Two or three parts side by side, like Mornye's bottom bar: an icon on a pill, its name under it.

    items: (icons, title). choose(index) when another one is pressed. Returns the row and a repaint(index)."""
    owner = screen.owner
    Params = jclass("android.widget.LinearLayout$LayoutParams")
    LinearLayout = jclass("android.widget.LinearLayout")
    ImageView = jclass("android.widget.ImageView")
    row = LinearLayout(owner.context)
    row.setOrientation(0)
    row.setPadding(_dp(12), _dp(4), _dp(12), _dp(8))
    parts = []
    for index, (icons, title) in enumerate(items):
        part = LinearLayout(owner.context)
        part.setOrientation(1)
        part.setGravity(1)
        icon = ImageView(owner.context)
        owner.set_icon(icon, icons)
        icon.setScaleType(jclass("android.widget.ImageView$ScaleType").CENTER)
        part.addView(icon, owner.params(64, 32))
        name = owner.text_view(12)
        name.setText(title)
        name.setGravity(1)
        place = Params(-2, -2)
        place.topMargin = _dp(4)
        part.addView(name, place)
        part.setContentDescription(title)
        screen.click(part, choose, index)
        row.addView(part, Params(0, _dp(60), 1.0))
        parts.append((icon, name))

    def paint(current):
        for index, (icon, name) in enumerate(parts):
            on = index == current
            icon.setBackground(owner.rounded(owner.color("tonal"), _dp(16)) if on else None)
            owner.tint(icon, owner.color("onTonal") if on else owner.color("textSecondary"))
            name.setTextColor(owner.color("text") if on else owner.color("textSecondary"))
            name.setTypeface(owner.bold if on else owner.regular)
            name.setSelected(on)

    paint(selected)
    return row, paint
