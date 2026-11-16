// Compile-time stand-in for exteraGram 13.1.1's PillRegistry, never packed into the DEX.
package com.exteragram.messenger.pillstack.core;

import android.content.Context;

import com.exteragram.messenger.pillstack.ui.pills.BasePill;

import org.telegram.ui.ActionBar.Theme;

public class PillRegistry {
    public interface PillCreator {
        BasePill create(Context context, Theme.ResourcesProvider resourcesProvider);
    }

    public static final class PillInfo {
        public PillInfo(int id, CharSequence name, int iconRes, int iconColorTop, int iconColorBottom, PillCreator creator) {
        }
    }

    public static void register(PillInfo info) {
    }

    public static void unregister(int id) {
    }
}
