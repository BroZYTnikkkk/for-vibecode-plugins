// Compile-time stand-in for exteraGram 13.1.1's PlayerCovers, never packed into the DEX.
package com.exteragram.messenger.player;

import org.telegram.messenger.ImageReceiver;
import org.telegram.messenger.MessageObject;

public final class PlayerCovers {
    public static boolean setCover(ImageReceiver receiver, MessageObject message, int size, boolean artwork) {
        return false;
    }
}
