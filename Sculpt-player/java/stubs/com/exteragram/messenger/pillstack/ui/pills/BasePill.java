// Compile-time stand-in for exteraGram 13.1.1's BasePill, never packed into the DEX.
package com.exteragram.messenger.pillstack.ui.pills;

import android.content.Context;
import android.view.View;
import android.widget.FrameLayout;

import org.telegram.ui.ActionBar.Theme;

public abstract class BasePill extends FrameLayout {
    public BasePill(Context context, Theme.ResourcesProvider resourcesProvider) {
        super(context);
    }

    public abstract int getPillId();

    public abstract long getRefreshInterval();

    public abstract void onPillClicked();

    public abstract boolean onPillLongClicked();

    public abstract void onUpdateData(boolean animated);

    public abstract void updateColors();

    public int getThemedColor(int key) {
        return 0;
    }

    public int getThemedColor(int key, float alpha) {
        return 0;
    }

    public void animateSizeChange() {
    }

    public void setLoadingTargetView(View view) {
    }
}
