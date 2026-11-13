// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
package sculpt;

import java.io.File;
import java.util.ArrayList;

import org.telegram.messenger.MessageObject;
import org.telegram.tgnet.TLRPC;

/**
 * Local MessageObjects for a queue, the same shape Telegram's attach menu uses.
 *
 * Built here rather than in Python: a queue of a thousand songs took a thousand rounds of field-by-field
 * calls across the bridge, which is the pause between a tap and the music.
 */
public final class Queue {

    private Queue() {
    }

    public static ArrayList<MessageObject> build(int account, long userId, int firstId, int date,
                                                 String[] paths, String[] titles, String[] artists, int[] durations) {
        ArrayList<MessageObject> out = new ArrayList<>(paths.length);
        for (int i = 0; i < paths.length; i++) {
            out.add(message(account, userId, firstId + i, date, paths[i], titles[i], artists[i], durations[i]));
        }
        return out;
    }

    /** The same, for songs whose ids do not go one after another: a queue that plays mixed keeps the ids of its list. */
    public static ArrayList<MessageObject> buildIds(int account, long userId, int[] ids, int date,
                                                    String[] paths, String[] titles, String[] artists, int[] durations) {
        ArrayList<MessageObject> out = new ArrayList<>(paths.length);
        for (int i = 0; i < paths.length; i++) {
            out.add(message(account, userId, ids[i], date, paths[i], titles[i], artists[i], durations[i]));
        }
        return out;
    }

    /**
     * The files of a queue's songs, one per line and in the list's order, in one call across the bridge; an
     * empty line for a song from a chat. Null when a path has a line break in it: the caller then asks one by one.
     */
    public static String paths(ArrayList<MessageObject> list) {
        StringBuilder out = new StringBuilder(list.size() * 64);
        for (int i = 0; i < list.size(); i++) {
            MessageObject message = list.get(i);
            String path = message != null && message.getId() < 0 && message.messageOwner != null ? message.messageOwner.attachPath : null;
            if (path != null && path.indexOf('\n') >= 0) {
                return null;
            }
            if (i > 0) {
                out.append('\n');
            }
            if (path != null) {
                out.append(path);
            }
        }
        return out.toString();
    }

    public static MessageObject message(int account, long userId, int id, int date,
                                        String path, String title, String artist, int duration) {
        TLRPC.TL_message message = new TLRPC.TL_message();
        message.id = id;
        message.out = true;
        TLRPC.TL_peerUser peer = new TLRPC.TL_peerUser();
        peer.user_id = userId;
        message.peer_id = peer;
        TLRPC.TL_peerUser from = new TLRPC.TL_peerUser();
        from.user_id = userId;
        message.from_id = from;
        message.date = date;
        message.message = "";
        message.attachPath = path;

        TLRPC.TL_messageMediaDocument media = new TLRPC.TL_messageMediaDocument();
        media.flags |= 3;
        TLRPC.TL_document document = new TLRPC.TL_document();
        media.document = document;
        message.media = media;
        message.flags |= 768;

        File file = new File(path);
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        String extension = dot >= 0 ? name.substring(dot + 1).toLowerCase() : "";
        if (extension.isEmpty()) {
            extension = "mp3";
        }
        document.id = 0;
        document.access_hash = 0;
        document.file_reference = new byte[0];
        document.date = date;
        document.mime_type = "audio/" + ("mp3".equals(extension) ? "mpeg" : extension);
        document.size = file.length();
        document.dc_id = 0;

        TLRPC.TL_documentAttributeAudio audio = new TLRPC.TL_documentAttributeAudio();
        audio.duration = duration;
        audio.title = title == null || title.isEmpty() ? name : title;
        audio.performer = artist == null ? "" : artist;
        audio.flags |= 3;
        document.attributes.add(audio);
        TLRPC.TL_documentAttributeFilename fileName = new TLRPC.TL_documentAttributeFilename();
        fileName.file_name = name;
        document.attributes.add(fileName);
        return new MessageObject(account, message, false, true);
    }
}
