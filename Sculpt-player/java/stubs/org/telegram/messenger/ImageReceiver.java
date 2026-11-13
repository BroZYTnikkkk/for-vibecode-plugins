// Compile-time stand-in for exteraGram 13.1.1's ImageReceiver, never packed into the DEX.
package org.telegram.messenger;

import android.graphics.Canvas;
import android.view.View;

public class ImageReceiver {
    public ImageReceiver(View parent) {
    }

    public void clearImage() {
    }

    public boolean draw(Canvas canvas) {
        return false;
    }

    public boolean onAttachedToWindow() {
        return false;
    }

    public void onDetachedFromWindow() {
    }

    public void setImageCoords(float x, float y, float width, float height) {
    }
}
