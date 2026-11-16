// Compile-time stand-in for exteraGram 13.1.1's TLRPC: only the fields Sculpt touches, with their real types.
// Never packed into the DEX; on the phone the code links against the app's own classes.
package org.telegram.tgnet;

import java.util.ArrayList;

public class TLRPC {

    public static class Message extends TLObject {
        public int date;
        public int flags;
        public Peer from_id;
        public int id;
        public MessageMedia media;
        public String message;
        public boolean out;
        public Peer peer_id;
        public String attachPath;
    }

    public static class TL_message extends Message {
    }

    public static abstract class Peer extends TLObject {
        public long user_id;
    }

    public static class TL_peerUser extends Peer {
    }

    public static abstract class MessageMedia extends TLObject {
        public Document document;
        public int flags;
    }

    public static class TL_messageMediaDocument extends MessageMedia {
    }

    public static abstract class Document extends TLObject {
        public long access_hash;
        public ArrayList<DocumentAttribute> attributes = new ArrayList<>();
        public int date;
        public int dc_id;
        public byte[] file_reference;
        public long id;
        public String mime_type;
        public long size;
    }

    public static class TL_document extends Document {
    }

    public static abstract class DocumentAttribute extends TLObject {
        public double duration;
        public String file_name;
        public int flags;
        public String performer;
        public String title;
    }

    public static class TL_documentAttributeAudio extends DocumentAttribute {
    }

    public static class TL_documentAttributeFilename extends DocumentAttribute {
    }
}
