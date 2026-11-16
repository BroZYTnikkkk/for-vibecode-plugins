// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
// The blur by distance follows Mornye's lyrics (Mornye by zarzet, https://github.com/mornyeapp/Mornye, LGPL-3.0-only).
package sculpt;

import android.animation.ValueAnimator;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.RenderEffect;
import android.graphics.Shader;
import android.os.Build;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.LinearInterpolator;
import android.view.animation.PathInterpolator;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;
import java.util.WeakHashMap;

/**
 * What the lyrics screen does every frame, kept out of Python: the lines' blur easing to a new focus, and the
 * blurred cover behind them. Static calls only: Python cannot hold objects of this DEX across a reinstall.
 */
public final class LyricsFx {

    private static final float[] SIGMA = {0f, 2.4f, 3.6f, 4.8f};  // by distance from the current line, as in Mornye
    private static final int NEAR = 7;  // lines farther than this are off the screen: they blur at once
    private static final long EASE_MS = 420;
    private static final int BACKDROP_SIZE = 96;
    private static final int BACKDROP_RADIUS = 4;
    private static final int DOTS_WIDTH_DP = 43;  // three dots of 9 dp, 7 dp apart, at the largest they pulse to

    private static final WeakHashMap<View, float[]> STATE = new WeakHashMap<>();  // value, from, to
    private static final Paint PAINT = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.ANTI_ALIAS_FLAG);
    private static final RectF RECT = new RectF();
    private static ValueAnimator animator;
    private static final long WAVE_MS = 800;
    private static final int WAVE_ROWS = 12;
    private static ValueAnimator waveAnimator;
    private static List<? extends View> waveLines;
    private static int waveCurrent = -1;

    private LyricsFx() {
    }

    public static void focus(List<? extends View> lines, int current, boolean blur, float density) {
        if (Build.VERSION.SDK_INT < 31 || lines == null) {
            return;
        }
        wave(lines, current, blur, density);
        if (animator != null) {
            animator.cancel();
            animator = null;
        }
        final List<View> moving = new ArrayList<>();
        for (int i = 0; i < lines.size(); i++) {
            View view = lines.get(i);
            int distance = current < 0 ? SIGMA.length - 1 : Math.abs(i - current);
            float target = blur ? SIGMA[Math.min(distance, SIGMA.length - 1)] * density : 0f;
            float[] state = STATE.get(view);
            if (state == null) {
                state = new float[3];
                STATE.put(view, state);
            }
            if (distance > NEAR) {
                state[0] = state[1] = state[2] = target;
                apply(view, target);
                continue;
            }
            state[1] = state[0];
            state[2] = target;
            if (state[1] != state[2]) {
                moving.add(view);
            }
        }
        if (moving.isEmpty()) {
            return;
        }
        ValueAnimator ease = ValueAnimator.ofFloat(0f, 1f);
        ease.setDuration(EASE_MS);
        ease.setInterpolator(new PathInterpolator(0.65f, 0f, 0.35f, 1f));
        ease.addUpdateListener(a -> {
            float t = (float) a.getAnimatedValue();
            for (View view : moving) {
                float[] state = STATE.get(view);
                if (state != null) {
                    state[0] = state[1] + (state[2] - state[1]) * t;
                    apply(view, state[0]);
                }
            }
        });
        animator = ease;
        ease.start();
    }

    /**
     * The liquid move, Mornye's LyricScrollMotion: the rows after the new line trail the scroll and catch up on a
     * spring, each 35 ms later than the one above it, so the list flows instead of sliding as one piece.
     */
    private static void wave(List<? extends View> lines, int current, boolean live, float density) {
        int previous = waveLines == lines ? waveCurrent : -1;
        waveLines = lines;
        waveCurrent = current;
        if (waveAnimator != null) {
            waveAnimator.cancel();
            waveAnimator = null;
        }
        final int size = lines.size();
        final int focus = current;
        float moved = 0f;
        if (live && previous >= 0 && current >= 0 && current < size && previous < size && Math.abs(current - previous) <= 2) {
            float limit = 96f * density;
            moved = Math.max(-limit, Math.min(limit, lines.get(current).getTop() - lines.get(previous).getTop()));
        }
        final float distance = moved;
        final List<View> rows = new ArrayList<>();
        final List<Float> starts = new ArrayList<>();
        final List<Integer> after = new ArrayList<>();
        for (int i = 0; i < size; i++) {
            View view = lines.get(i);
            int below = current >= 0 ? i - current : 0;
            float start = view.getTranslationY();
            if (start != 0f || (distance != 0f && below > 0 && below <= WAVE_ROWS)) {
                rows.add(view);
                starts.add(start);
                after.add(below);
            }
        }
        if (rows.isEmpty()) {
            return;
        }
        ValueAnimator flow = ValueAnimator.ofFloat(0f, WAVE_MS / 1000f);
        flow.setDuration(WAVE_MS);
        flow.setInterpolator(new LinearInterpolator());
        flow.addUpdateListener(a -> {
            float t = (float) a.getAnimatedValue();
            float scroll = scrollCurve(t);
            boolean last = a.getAnimatedFraction() >= 1f;
            for (int n = 0; n < rows.size(); n++) {
                float offset = starts.get(n) * (1f - scroll);
                int below = after.get(n);
                if (below > 0 && below <= WAVE_ROWS && distance != 0f) {
                    float delay = Math.min(below, 6) * 0.035f;
                    offset += distance * (scroll - (t <= delay ? 0f : follow(t - delay)));
                }
                rows.get(n).setTranslationY(last ? 0f : offset);
            }
        });
        waveAnimator = flow;
        flow.start();
    }

    /** Critically damped, stiffness 196, reaching exactly 1 at 550 ms. */
    private static float scrollCurve(float t) {
        return Math.min(1f, critical(t) / critical(0.55f));
    }

    private static float critical(float t) {
        return 1f - (float) Math.exp(-14f * t) * (1f + 14f * t);
    }

    /** Stiffness 121, damping ratio 0.85: the small overshoot is the liquid part. */
    private static float follow(float t) {
        float decay = 0.85f * 11f;
        float wave = 11f * (float) Math.sqrt(1f - 0.85f * 0.85f);
        return 1f - (float) Math.exp(-decay * t) * ((float) Math.cos(wave * t) + decay / wave * (float) Math.sin(wave * t));
    }

    private static void apply(View view, float radius) {
        view.setRenderEffect(radius < 0.5f ? null : RenderEffect.createBlurEffect(radius, radius, Shader.TileMode.DECAL));
    }

    /** 0 left, 1 center, 2 right; the line's focus scale grows from the same side. */
    public static void align(List<? extends View> lines, final int mode) {
        if (lines == null) {
            return;
        }
        int gravity = mode == 1 ? android.view.Gravity.CENTER_HORIZONTAL : mode == 2 ? android.view.Gravity.END : android.view.Gravity.START;
        for (final View view : lines) {
            if (view instanceof TextView) {
                ((TextView) view).setGravity(gravity);
            }
            view.post(() -> view.setPivotX(mode == 0 ? 0f : mode == 2 ? view.getWidth() : view.getWidth() / 2f));
        }
        // the three dots of a pause fill their row and draw from its left edge: only a row as wide as they are can move
        if (!lines.isEmpty() && lines.get(0).getParent() instanceof ViewGroup) {
            ViewGroup column = (ViewGroup) lines.get(0).getParent();
            for (int i = 0; i < column.getChildCount(); i++) {
                View child = column.getChildAt(i);
                if ("DotsView".equals(child.getClass().getSimpleName()) && child.getLayoutParams() instanceof LinearLayout.LayoutParams) {
                    LinearLayout.LayoutParams place = (LinearLayout.LayoutParams) child.getLayoutParams();
                    place.width = mode == 0 ? ViewGroup.LayoutParams.MATCH_PARENT : Math.round(DOTS_WIDTH_DP * child.getResources().getDisplayMetrics().density);
                    place.gravity = gravity;
                    child.setLayoutParams(place);
                }
            }
        }
    }

    /** The cover made tiny and box-blurred once: drawn large, it costs one bitmap per frame and no blur at all. */
    public static Bitmap backdrop(Bitmap source) {
        if (source == null || source.isRecycled()) {
            return null;
        }
        Bitmap software = source.getConfig() == Bitmap.Config.HARDWARE ? source.copy(Bitmap.Config.ARGB_8888, false) : source;
        if (software == null) {
            return null;
        }
        int size = BACKDROP_SIZE;
        Bitmap small = Bitmap.createScaledBitmap(software, size, size, true);
        int[] pixels = new int[size * size];
        small.getPixels(pixels, 0, size, 0, 0, size, size);
        int[] buffer = new int[pixels.length];
        for (int pass = 0; pass < 2; pass++) {
            box(pixels, buffer, size, 1, size);
            box(buffer, pixels, size, size, 1);
        }
        return Bitmap.createBitmap(pixels, size, size, Bitmap.Config.ARGB_8888);
    }

    /** One direction of a box blur over a square; step walks along the line, next moves to the following line. */
    private static void box(int[] in, int[] out, int size, int step, int next) {
        int span = BACKDROP_RADIUS * 2 + 1;
        for (int line = 0; line < size; line++) {
            int start = line * next;
            int r = 0;
            int g = 0;
            int b = 0;
            for (int i = -BACKDROP_RADIUS; i <= BACKDROP_RADIUS; i++) {
                int c = in[start + clamp(i, size) * step];
                r += (c >> 16) & 255;
                g += (c >> 8) & 255;
                b += c & 255;
            }
            for (int i = 0; i < size; i++) {
                out[start + i * step] = 0xff000000 | ((r / span) << 16) | ((g / span) << 8) | (b / span);
                int gone = in[start + clamp(i - BACKDROP_RADIUS, size) * step];
                int come = in[start + clamp(i + BACKDROP_RADIUS + 1, size) * step];
                r += ((come >> 16) & 255) - ((gone >> 16) & 255);
                g += ((come >> 8) & 255) - ((gone >> 8) & 255);
                b += (come & 255) - (gone & 255);
            }
        }
    }

    private static int clamp(int value, int size) {
        return value < 0 ? 0 : Math.min(value, size - 1);
    }

    /** The blurred cover across the screen, darkened so the words read on a light cover. */
    public static void draw(Canvas canvas, Bitmap backdrop, int width, int height, float alpha, float scrim) {
        if (backdrop != null && !backdrop.isRecycled()) {
            float side = Math.max(width, height);
            RECT.set((width - side) / 2f, (height - side) / 2f, (width + side) / 2f, (height + side) / 2f);
            PAINT.setAlpha((int) (255 * alpha));
            canvas.drawBitmap(backdrop, null, RECT, PAINT);
        }
        canvas.drawColor(Color.argb((int) (255 * scrim * alpha), 0, 0, 0));
    }
}
