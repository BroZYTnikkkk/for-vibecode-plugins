// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
package sculpt;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.os.SystemClock;
import android.view.View;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;

/**
 * The visualizer's bars, moved out of Python: their heights follow the bands, and they are laid out and painted
 * here. Python asks for a new layout 40 times a second and for a paint on every frame, one call each; before, each
 * frame took a few dozen calls across the bridge and every layout a few hundred lines of Python.
 *
 * Static state only: Python cannot hold objects of this DEX across a reinstall. There is one player at a time.
 */
public final class Bars {

    private static final int LAYERS = 3;
    private static final int PARAMS = 7;  // shift, rise, fall, gain, depth, speed, phase

    private static float[][] values = new float[LAYERS][0];
    private static double lastTime;

    // what build() laid out, one batch per layer drawn, the back layer first
    private static final float[][] body = new float[LAYERS][0];
    private static final float[][] tips = new float[LAYERS][0];
    private static final float[][] corners = new float[LAYERS][0];
    private static final int[] bodyCount = new int[LAYERS];
    private static final int[] tipCount = new int[LAYERS];
    private static final int[] cornerCount = new int[LAYERS];
    private static final int[] batchColor = new int[LAYERS];
    private static final boolean[] batchColored = new boolean[LAYERS];
    private static final float[] batchWidth = new float[LAYERS];
    private static int batches;
    private static boolean square;
    private static float tipWidth;
    private static float cornerWidth;
    private static int alpha;
    private static boolean moving;
    private static float centerX;
    private static float centerY;

    // frame(): what the player's views say, read here by reflection with the lookups kept
    public static final int LYRICS = 1;  // the lyrics are opening or open: Python draws their backdrop
    public static final int VIDEO = 2;  // a Spotify Canvas video stands where the cover was: nothing over it
    public static final int BUILD = 4;  // time to lay the bars out again (Python reads the bands and calls build)
    private static final long BUILD_MS = 24;
    private static final HashMap<String, Field> FIELDS = new HashMap<>();
    private static final HashMap<String, Method> METHODS = new HashMap<>();
    private static Method paused;
    private static Object media;
    private static long builtAt;
    private static float builtLeft = -1f;
    private static float builtSize = -1f;
    private static float builtTop = -1f;
    private static float builtMode = -1f;
    private static float builtScale = -1f;
    private static float lastMode;

    private Bars() {
    }

    /** The heights ease towards the bands; true while any bar still shows. */
    public static boolean advance(float[] bands, float[] params, int count, boolean layered, double now) {
        double dt = lastTime > 0 ? Math.min(0.1, now - lastTime) : 0.016;
        lastTime = now;
        boolean moving = false;
        int last = bands.length - 1;
        float scale = last / (float) Math.max(1, count - 1);
        int layerCount = layered ? LAYERS : 1;
        for (int layer = 0; layer < layerCount; layer++) {
            if (values[layer].length != count) {
                values[layer] = new float[count];
            }
            float[] row = values[layer];
            int p = layer * PARAMS;
            float shift = params[p];
            float rise = (float) Math.min(1.0, dt * params[p + 1]);
            float fall = (float) Math.min(1.0, dt * params[p + 2]);
            float gain = layered ? params[p + 3] : 1f;
            float depth = params[p + 4];
            float speed = params[p + 5];
            float phase = params[p + 6];
            for (int i = 0; i < count; i++) {
                float at = Math.max(0f, Math.min((float) last, i * scale + shift));
                int low = (int) at;
                int high = Math.min(last, low + 1);
                float target = (bands[low] + (bands[high] - bands[low]) * (at - low)) * gain;
                if (depth != 0f) {
                    target *= (float) (1.0 - depth + depth * (0.5 + 0.5 * Math.sin(now * speed + i * phase)));
                }
                float value = row[i];
                value += (target - value) * (target > value ? rise : fall);
                row[i] = value;
                if (value > 0.005f) {
                    moving = true;
                }
            }
        }
        Bars.moving = moving;
        return moving;
    }

    /**
     * Lays the bars out. geometry: left, step, inside, width, radius, offset, then (base, sign, height) per row.
     * flags: layered, style, strip, alpha, row count, count. colors: one per layer, or null for the shader's.
     */
    public static void build(float[] geometry, int[] flags, int[] colors) {
        boolean layered = flags[0] != 0;
        int style = flags[1];
        boolean strip = flags[2] != 0;
        alpha = flags[3];
        int rows = flags[4];
        int count = flags[5];
        float left = geometry[0];
        float step = geometry[1];
        float inside = geometry[2];
        float width = geometry[3];
        float radius = geometry[4];
        float offset = geometry[5];
        float half = step / 2f;
        centerX = geometry[6 + rows * 3];
        centerY = geometry[7 + rows * 3];
        builtLeft = geometry[8 + rows * 3];
        builtSize = geometry[9 + rows * 3];
        builtTop = geometry[10 + rows * 3];
        builtMode = geometry[11 + rows * 3];
        builtScale = geometry[12 + rows * 3];
        builtAt = SystemClock.uptimeMillis();
        square = style == 0;
        tipWidth = width - 2f * radius;
        cornerWidth = 2f * radius;
        batches = 0;
        int[] order = layered ? new int[] {2, 1, 0} : new int[] {0};
        for (int layer : order) {
            float[] row = values[layer];
            if (row.length < count) {
                continue;
            }
            int b = batches;
            int needed = rows * count * 4;
            if (body[b].length < needed) {
                body[b] = new float[needed];
                tips[b] = new float[needed];
                corners[b] = new float[needed];
            }
            int nb = 0;
            int nt = 0;
            int nc = 0;
            for (int r = 0; r < rows; r++) {
                float base = geometry[6 + r * 3];
                float sign = geometry[7 + r * 3];
                float height = geometry[8 + r * 3];
                float start = base - sign * inside;
                for (int i = 0; i < count; i++) {
                    float value = row[i];
                    if (value <= 0.005f) {
                        continue;
                    }
                    if (layered) {
                        boolean hidden = false;
                        for (int front = 0; front < layer; front++) {
                            if (values[front].length > i && values[front][i] >= value) {
                                hidden = true;  // what a layer in front covers is not drawn at all
                                break;
                            }
                        }
                        if (hidden) {
                            continue;
                        }
                    }
                    float x = left + half + i * step;
                    float reach = height * value;
                    if (strip) {
                        // a bar shorter than its own rounded top would poke through the line
                        reach = Math.max(reach, square ? 2f * radius : width);
                    }
                    float tip = base + sign * reach;
                    float[] lines = body[b];
                    if (!square) {
                        lines[nb++] = x;
                        lines[nb++] = start;
                        lines[nb++] = x;
                        lines[nb++] = tip;
                        continue;
                    }
                    float neck = tip - sign * radius;
                    lines[nb++] = x;
                    lines[nb++] = start;
                    lines[nb++] = x;
                    lines[nb++] = neck;
                    float[] t = tips[b];
                    t[nt++] = x;
                    t[nt++] = neck - sign;
                    t[nt++] = x;
                    t[nt++] = tip;
                    float[] c = corners[b];
                    c[nc++] = x - offset;
                    c[nc++] = neck;
                    c[nc++] = x + offset;
                    c[nc++] = neck;
                }
            }
            if (nb == 0) {
                continue;
            }
            bodyCount[b] = nb;
            tipCount[b] = nt;
            cornerCount[b] = nc;
            batchColored[b] = layered && colors != null;
            batchColor[b] = batchColored[b] ? colors[layer] : 0;
            batchWidth[b] = width;
            batches++;
        }
    }

    /** One frame of the bars as laid out; fade dims them while a finger swipes the cover. */
    public static void paint(Canvas canvas, Paint paint, float fade) {
        int faded = (int) (alpha * fade);
        for (int b = 0; b < batches; b++) {
            if (batchColored[b]) {
                int color = batchColor[b];
                paint.setARGB(faded, (color >> 16) & 255, (color >> 8) & 255, color & 255);
            } else {
                paint.setAlpha(faded);
            }
            paint.setStrokeCap(square ? Paint.Cap.BUTT : Paint.Cap.ROUND);
            paint.setStrokeWidth(batchWidth[b]);
            canvas.drawLines(body[b], 0, bodyCount[b], paint);
            if (square) {
                // slightly rounded rectangles in three batches, far cheaper than a drawRoundRect call per bar
                paint.setStrokeWidth(tipWidth);
                canvas.drawLines(tips[b], 0, tipCount[b], paint);
                paint.setStrokeCap(Paint.Cap.ROUND);
                paint.setStrokeWidth(cornerWidth);
                canvas.drawPoints(corners[b], 0, cornerCount[b], paint);
            }
        }
    }

    /** Nothing to draw (both rows switched off): frames paint nothing until the next build. */
    public static void clear() {
        batches = 0;
        builtAt = SystemClock.uptimeMillis();
    }

    /** How far the lyrics are open, as the last frame read it. */
    public static float mode() {
        return lastMode;
    }

    /**
     * One frame of the visualizer, with one call from Python: reads the player's state, paints the bars as laid out
     * (following a finger that swipes the cover) and asks for the next frame while anything moves.
     * Returns LYRICS, VIDEO and BUILD flags.
     */
    public static int frame(Canvas canvas, Paint paint, Object sheet, Object layout, Object cover) {
        try {
            float mode = Math.max(0f, Math.min(1f, getFloat(sheet, "modeProgress")));
            lastMode = mode;
            int flags = mode > 0.003f ? LYRICS : 0;
            // the sheet's own canvasProgress: the cover view never goes into its Canvas mode (NoCanvasHook)
            if (mode < 0.5f && getFloat(sheet, "canvasProgress") > 0.01f) {
                return flags | VIDEO;
            }
            float scale = getFloat(cover, "pauseScale");
            float left = getFloat(layout, "coverLeft");
            float size = getFloat(layout, "coverSize");
            float top = getFloat(layout, "coverTop");
            if (SystemClock.uptimeMillis() - builtAt >= BUILD_MS || left != builtLeft || size != builtSize || top != builtTop
                    || Math.abs(mode - builtMode) > 0.001f || Math.abs(scale - builtScale) > 0.0005f) {
                flags |= BUILD;
            }
            float offset = call(cover, "getPageOffset");
            float fade = 1f;
            if (offset != 0f) {
                float page = call(cover, "getPageWidth");
                float pager = getFloat(cover, "pager");
                float amount = page > 0 ? (1f - pager) * Math.min(1f, Math.abs(offset) / page) : 0f;
                float shrink = 1f + (0.86f - 1f) * amount;
                fade = 1f + (0.55f - 1f) * amount;
                canvas.save();
                canvas.translate(offset, 0f);
                canvas.scale(shrink, shrink, centerX, centerY);
            }
            paint(canvas, paint, fade);
            if (offset != 0f) {
                canvas.restore();
            }
            // the cover redraws only itself while it slides: the layer under it is asked for each frame here
            if (!isPaused() || moving || offset != 0f || (scale > 0.941f && scale < 0.999f)) {
                ((View) layout).postInvalidateOnAnimation();
            }
            return flags;
        } catch (Throwable error) {
            return BUILD | 8;  // 8: this way failed, Python draws by itself
        }
    }

    private static Field field(Object owner, String name) throws NoSuchFieldException {
        String key = owner.getClass().getName() + "#" + name;
        Field found = FIELDS.get(key);
        if (found == null) {
            for (Class<?> c = owner.getClass(); c != null && found == null; c = c.getSuperclass()) {
                try {
                    found = c.getDeclaredField(name);
                } catch (NoSuchFieldException ignored) {
                    // a field of a superclass
                }
            }
            if (found == null) {
                throw new NoSuchFieldException(name);
            }
            found.setAccessible(true);
            FIELDS.put(key, found);
        }
        return found;
    }

    private static float getFloat(Object owner, String name) throws Exception {
        return field(owner, name).getFloat(owner);
    }

    private static float call(Object owner, String name) throws Exception {
        String key = owner.getClass().getName() + "#" + name;
        Method found = METHODS.get(key);
        if (found == null) {
            found = owner.getClass().getMethod(name);
            METHODS.put(key, found);
        }
        Object value = found.invoke(owner);
        return value instanceof Number ? ((Number) value).floatValue() : 0f;
    }

    private static boolean isPaused() throws Exception {
        if (paused == null) {
            Class<?> controller = Class.forName("org.telegram.messenger.MediaController", false, Bars.class.getClassLoader());
            media = controller.getMethod("getInstance").invoke(null);
            paused = controller.getMethod("isMessagePaused");
        }
        return (Boolean) paused.invoke(media);
    }

    /** The player closed: the bars start from nothing next time. */
    public static void reset() {
        for (int layer = 0; layer < LAYERS; layer++) {
            values[layer] = new float[0];
        }
        batches = 0;
        lastTime = 0;
    }
}
