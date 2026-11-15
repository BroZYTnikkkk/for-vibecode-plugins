// Compile-time stand-in for Telegram's Theme, never packed into the DEX.
package org.telegram.ui.ActionBar;

public class Theme {
    public static int key_windowBackgroundWhite;
    public static int key_windowBackgroundWhiteBlackText;

    public interface ResourcesProvider {
    }

    public static boolean isCurrentThemeDark() {
        return false;
    }
}
