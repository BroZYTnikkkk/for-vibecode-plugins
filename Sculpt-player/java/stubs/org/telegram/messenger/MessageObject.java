// Compile-time stand-in for exteraGram 13.1.1's MessageObject, never packed into the DEX.
package org.telegram.messenger;

import org.telegram.tgnet.TLRPC;

public class MessageObject {
    public MessageObject(int account, TLRPC.Message message, boolean generateLayout, boolean checkMediaExists) {
    }
}
