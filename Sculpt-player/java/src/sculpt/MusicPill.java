// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
package sculpt;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.exteragram.messenger.pillstack.ui.pills.BasePill;

import org.telegram.ui.ActionBar.Theme;

import java.util.Collections;
import java.util.Set;
import java.util.WeakHashMap;

/**
 * A pill of exteraGram's pill stack beside the chats' search: a note and the song that plays, or the player's name.
 * A tap opens the player. Made by PillRegistry through the plugin's creator; what it says and does is set from
 * Python through the static methods, so Python never holds one of these.
 */
public final class MusicPill extends BasePill {
    public static final int ID = 731001;

    private static Runnable click;
    private static String text = "Sculpt Player";
    private static final Set<MusicPill> shown = Collections.newSetFromMap(new WeakHashMap<>());

    private final LinearLayout layout;
    private final ImageView iconView;
    private final TextView textView;

    public MusicPill(Context context, Theme.ResourcesProvider resourcesProvider) {
        super(context, resourcesProvider);
        float density = context.getResources().getDisplayMetrics().density;
        layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setGravity(Gravity.CENTER);
        layout.setMinimumWidth(Math.round(48 * density));
        layout.setPadding(Math.round(8 * density), 0, Math.round(10 * density), 0);
        addView(layout, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, Math.round(28 * density),
                Gravity.END | Gravity.CENTER_VERTICAL));
        iconView = new ImageView(context);
        iconView.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        int icon = context.getResources().getIdentifier("msg_played", "drawable", context.getPackageName());
        if (icon != 0) {
            iconView.setImageResource(icon);
        }
        LinearLayout.LayoutParams iconPlace = new LinearLayout.LayoutParams(Math.round(16 * density), Math.round(16 * density));
        iconPlace.setMarginEnd(Math.round(4 * density));
        iconPlace.gravity = Gravity.CENTER_VERTICAL;
        layout.addView(iconView, iconPlace);
        textView = new TextView(context);
        textView.setTextSize(13);
        textView.setTypeface(Typeface.DEFAULT_BOLD);
        textView.setSingleLine(true);
        textView.setEllipsize(TextUtils.TruncateAt.END);
        textView.setMaxWidth(Math.round(160 * density));
        textView.setIncludeFontPadding(false);
        layout.addView(textView, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        setLoadingTargetView(layout);
        shown.add(this);
        updateColors();
        onUpdateData(false);
    }

    /**
     * From Python: the pill in exteraGram's registry, made here. Python never holds an object of this DEX's classes:
     * after a reinstall Chaquopy cannot make a proxy of a class loaded again, so the creator lives in Java.
     */
    public static void register(String title, int icon, int colorTop, int colorBottom) {
        com.exteragram.messenger.pillstack.core.PillRegistry.register(
                new com.exteragram.messenger.pillstack.core.PillRegistry.PillInfo(ID, title, icon, colorTop, colorBottom,
                        MusicPill::new));
    }

    public static void unregister() {
        com.exteragram.messenger.pillstack.core.PillRegistry.unregister(ID);
    }

    /** From Python: what a tap does (posted on the UI thread by the caller's own runnable). */
    public static void setClick(Runnable action) {
        click = action;
    }

    /** From Python, on the UI thread: the words on every pill shown now. */
    public static void setText(String value) {
        text = value == null || value.isEmpty() ? "Sculpt Player" : value;
        for (MusicPill pill : shown.toArray(new MusicPill[0])) {
            pill.onUpdateData(true);
        }
    }

    public static void release() {
        click = null;
        shown.clear();
    }

    @Override
    public int getPillId() {
        return ID;
    }

    @Override
    public long getRefreshInterval() {
        return 0L;
    }

    @Override
    public void onPillClicked() {
        Runnable action = click;
        if (action != null) {
            action.run();
        }
    }

    @Override
    public boolean onPillLongClicked() {
        return false;
    }

    @Override
    public void onUpdateData(boolean animated) {
        if (!TextUtils.equals(textView.getText(), text)) {
            if (animated) {
                animateSizeChange();
            }
            textView.setText(text);
        }
        textView.setContentDescription(text);
    }

    @Override
    public void updateColors() {
        int color = getThemedColor(Theme.key_windowBackgroundWhiteBlackText, 0.75f);
        int plate = Theme.isCurrentThemeDark() ? getThemedColor(Theme.key_windowBackgroundWhite)
                : (color & 0x00ffffff) | 0x17000000;
        GradientDrawable shape = new GradientDrawable();
        shape.setCornerRadius(14 * getResources().getDisplayMetrics().density);
        shape.setColor(plate);
        int ripple = (color & 0x00ffffff) | 0x1a000000;
        layout.setBackground(new RippleDrawable(ColorStateList.valueOf(ripple), shape, null));
        textView.setTextColor(color == 0 ? Color.GRAY : color);
        iconView.setColorFilter(new PorterDuffColorFilter(color, PorterDuff.Mode.SRC_IN));
    }

    @Override
    public void setPressed(boolean pressed) {
        super.setPressed(pressed);
        layout.setPressed(pressed);
    }
}
