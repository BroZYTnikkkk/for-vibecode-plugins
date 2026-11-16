// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
package sculpt;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.RecordingCanvas;
import android.graphics.RenderEffect;
import android.graphics.RenderNode;
import android.graphics.Shader;
import android.os.Build;

import org.telegram.messenger.ImageReceiver;

import java.lang.reflect.Field;

/**
 * The Spotify Canvas video under one of the plugin's tabs: drawn again, blurred and dimmed, over the sharp one the
 * player has just drawn, so the tab reads well and the video still moves behind it. Called from the layout's
 * onDraw, after the player's own background.
 */
public final class CanvasFx {
    private static Field slotsField;
    private static Field receiverField;
    private static Field thumbField;
    private static boolean broken;

    private static RenderNode node;
    private static float nodeRadius = -1f;
    private static final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.ANTI_ALIAS_FLAG);
    private static final Paint scrim = new Paint();
    private static final Rect src = new Rect();
    private static final RectF dst = new RectF();

    // the fallback without RenderEffect: the frame shrunk to a few dozen pixels and stretched back
    private static Bitmap small;
    private static Canvas smallCanvas;

    private CanvasFx() {
    }

    /**
     * background: the player's SpotifyCanvasBackground. amount: 0..1, how far the blur has come in.
     * radius: the blur radius in pixels. scrimColor: drawn over the blur at dim (0..1) times amount.
     * Returns false when there was no frame to draw.
     */
    public static boolean blur(Object background, Canvas canvas, RectF rect, float amount, float radius,
                               int scrimColor, float dim) {
        if (amount <= 0f || rect.isEmpty() || background == null) {
            return false;
        }
        Bitmap frame = frame(background);
        if (frame == null || frame.isRecycled() || frame.getWidth() <= 0 || frame.getHeight() <= 0) {
            return false;
        }
        float w = rect.width();
        float h = rect.height();
        // centre crop, as the ImageReceiver draws the video
        float scale = Math.max(w / frame.getWidth(), h / frame.getHeight());
        int sw = Math.round(w / scale);
        int sh = Math.round(h / scale);
        int sx = (frame.getWidth() - sw) / 2;
        int sy = (frame.getHeight() - sh) / 2;
        src.set(sx, sy, sx + sw, sy + sh);
        canvas.save();
        canvas.clipRect(rect);
        if (Build.VERSION.SDK_INT >= 31 && canvas.isHardwareAccelerated()) {
            if (node == null) {
                node = new RenderNode("sculptCanvasBlur");
            }
            node.setPosition(0, 0, Math.round(w), Math.round(h));
            if (nodeRadius != radius) {
                nodeRadius = radius;
                node.setRenderEffect(RenderEffect.createBlurEffect(radius, radius, Shader.TileMode.CLAMP));
            }
            RecordingCanvas recording = node.beginRecording();
            dst.set(0, 0, w, h);
            recording.drawBitmap(frame, src, dst, paint);
            node.endRecording();
            node.setAlpha(Math.min(1f, amount));
            canvas.translate(rect.left, rect.top);
            canvas.drawRenderNode(node);
            canvas.translate(-rect.left, -rect.top);
        } else {
            int tw = 36;
            int th = Math.max(1, Math.round(tw * h / w));
            if (small == null || small.getWidth() != tw || small.getHeight() != th) {
                small = Bitmap.createBitmap(tw, th, Bitmap.Config.ARGB_8888);
                smallCanvas = new Canvas(small);
            }
            dst.set(0, 0, tw, th);
            paint.setAlpha(255);
            smallCanvas.drawBitmap(frame, src, dst, paint);
            paint.setAlpha(Math.round(255 * Math.min(1f, amount)));
            canvas.drawBitmap(small, null, rect, paint);
            paint.setAlpha(255);
        }
        scrim.setColor(scrimColor);
        scrim.setAlpha(Math.round(255 * Math.min(1f, amount) * dim));
        canvas.drawRect(rect, scrim);
        canvas.restore();
        return true;
    }

    private static Bitmap frame(Object background) {
        if (broken) {
            return null;
        }
        try {
            if (slotsField == null) {
                slotsField = background.getClass().getDeclaredField("slots");
                slotsField.setAccessible(true);
            }
            Object[] slots = (Object[]) slotsField.get(background);
            if (slots == null || slots.length < 2 || slots[1] == null) {
                return null;
            }
            Object slot = slots[1];
            if (receiverField == null) {
                receiverField = slot.getClass().getDeclaredField("receiver");
                receiverField.setAccessible(true);
                thumbField = slot.getClass().getDeclaredField("thumbReceiver");
                thumbField.setAccessible(true);
            }
            Bitmap bitmap = ((ImageReceiver) receiverField.get(slot)).getBitmap();
            if (bitmap == null) {
                bitmap = ((ImageReceiver) thumbField.get(slot)).getBitmap();
            }
            return bitmap;
        } catch (Throwable t) {
            broken = true;  // another build of the app: the tab simply shows the sharp video
            return null;
        }
    }

    // -- the video inside the big cover instead of behind the whole player (setting canvas_place)

    private static Field sheetCanvas;
    private static Field sheetProgress;
    private static Field sheetMode;
    private static Field coverRadius;
    private static java.lang.reflect.Method checkVideo;
    private static java.lang.reflect.Method coverRect;
    private static java.lang.reflect.Method pageOffset;
    private static boolean coverBroken;
    public static String why = "";  // the last answer of inCover, for the log
    private static final RectF square = new RectF();

    /**
     * Called after the cover view drew itself: the current song's Canvas video in the cover's square, rounded like
     * it, moved by a swipe like it. Returns true while a video was drawn.
     */
    public static boolean inCover(Object sheet, Object cover, Canvas canvas) {
        if (coverBroken) {
            return false;
        }
        try {
            if (sheetCanvas == null) {
                Class<?> type = sheet.getClass();
                sheetCanvas = field(type, "spotifyCanvas");
                sheetProgress = field(type, "canvasProgress");
                sheetMode = field(type, "modeProgress");
                coverRadius = field(cover.getClass(), "radius");
                coverRect = cover.getClass().getMethod("getCoverRect");
                pageOffset = cover.getClass().getMethod("getPageOffset");
            }
            float shown = Math.max(0f, Math.min(1f, sheetProgress.getFloat(sheet)))
                    * (1f - Math.max(0f, Math.min(1f, sheetMode.getFloat(sheet))));
            if (shown <= 0.01f) {
                why = "no canvas shown";
                return false;
            }
            Object background = sheetCanvas.get(sheet);
            if (background == null) {
                why = "no background";
                return false;
            }
            Field slotsOf = background.getClass().getDeclaredField("slots");
            slotsOf.setAccessible(true);
            Object[] slots = (Object[]) slotsOf.get(background);
            if (slots == null || slots.length < 2 || slots[1] == null) {
                why = "no slot";
                return false;
            }
            Object slot = slots[1];
            if (checkVideo == null) {
                checkVideo = slot.getClass().getDeclaredMethod("checkVideo");
                checkVideo.setAccessible(true);
            }
            boolean video = (Boolean) checkVideo.invoke(slot);
            Field which = slot.getClass().getDeclaredField(video ? "receiver" : "thumbReceiver");
            which.setAccessible(true);
            ImageReceiver receiver = (ImageReceiver) which.get(slot);
            if (receiver == null) {
                why = "no receiver, video " + video;
                return false;
            }
            RectF rect = (RectF) coverRect.invoke(cover);
            float offset = (Float) pageOffset.invoke(cover);
            square.set(rect);
            square.offset(offset, 0f);
            receiver.setRoundRadius(Math.round(coverRadius.getFloat(cover)));
            receiver.setImageCoords(square.left, square.top, square.width(), square.height());
            receiver.setAlpha(shown);
            receiver.draw(canvas);
            why = "drew video=" + video + " at " + square;
            return true;
        } catch (Throwable t) {
            why = "broken: " + t;
            coverBroken = true;  // another build of the app: the video stays behind the player as exteraGram has it
            return false;
        }
    }

    private static Field field(Class<?> type, String name) throws NoSuchFieldException {
        Field found = type.getDeclaredField(name);
        found.setAccessible(true);
        return found;
    }

    public static String why() {
        return why;
    }

    public static void release() {
        sheetCanvas = null;
        sheetProgress = null;
        sheetMode = null;
        coverRadius = null;
        checkVideo = null;
        coverRect = null;
        pageOffset = null;
        coverBroken = false;
        releaseBlur();
    }

    private static void releaseBlur() {
        if (node != null) {
            node.discardDisplayList();
        }
        node = null;
        nodeRadius = -1f;
        small = null;
        smallCanvas = null;
        broken = false;
        slotsField = null;
        receiverField = null;
        thumbField = null;
    }
}
