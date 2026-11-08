// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
package sculpt;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Outline;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.text.TextUtils;
import android.util.LruCache;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.recyclerview.widget.ItemTouchHelper;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The songs of one queue, as Musicolet shows them: a handle to drag, the cover, title, author and album, the
 * length, and a menu button; the current song in a frame of the accent colour.
 *
 * The Python side owns the data and gets events through a Handler.Callback (an interface Chaquopy can
 * implement): ROW (arg1 = position), MENU (arg1 = position, obj = the button), MOVED (arg1 = from, arg2 = to,
 * sent once when the finger is lifted).
 */
public class QueueList extends RecyclerView {
    public static final int ROW = 1;
    public static final int MENU = 2;
    public static final int MOVED = 3;

    private static final LruCache<String, Bitmap> COVERS = new LruCache<String, Bitmap>(8 * 1024 * 1024) {
        @Override
        protected int sizeOf(String key, Bitmap value) {
            return value.getByteCount();
        }
    };
    private static final ExecutorService DECODER = Executors.newSingleThreadExecutor();

    private final Handler.Callback events;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Rows adapter = new Rows();
    private final LinearLayoutManager manager;
    private final ItemTouchHelper dragger;

    private String[] titles = new String[0];
    private String[] artists = new String[0];
    private String[] albums = new String[0];
    private String[] times = new String[0];
    private String[] covers = new String[0];
    private int current = -1;
    private boolean dragEnabled = true;
    private int dragFrom = -1;
    private int dragTo = -1;

    private int textColor = 0xffffffff;
    private int secondaryColor = 0xffaaaaaa;
    private int accentColor = 0xff88ccff;
    private int iconColor = 0xffffffff;
    private int coverColor = 0x22ffffff;
    private int handleIcon;
    private int menuIcon;

    // -- what Python calls -----------------------------------------------------------------
    //
    // Python never holds a QueueList: a reinstalled plugin loads this DEX again, and Chaquopy, still keeping
    // the first QueueList class by name, cannot wrap an object of the new one (whatever type it is read as).
    // So the list lives inside a plain FrameLayout that Python owns, and every call goes through it.

    public static void attach(Context context, Handler.Callback events, ViewGroup holder) {
        holder.addView(new QueueList(context, events), new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private static QueueList in(ViewGroup holder) {
        for (int i = 0; i < holder.getChildCount(); i++) {
            View child = holder.getChildAt(i);
            if (child instanceof QueueList) {
                return (QueueList) child;
            }
        }
        return null;
    }

    public static void rows(ViewGroup holder, String[] titles, String[] artists, String[] albums, String[] times, String[] covers, int current) {
        QueueList list = in(holder);
        if (list != null) {
            list.setRows(titles, artists, albums, times, covers, current);
        }
    }

    public static void current(ViewGroup holder, int position) {
        QueueList list = in(holder);
        if (list != null) {
            list.setCurrent(position);
        }
    }

    public static void cover(ViewGroup holder, int position, String path) {
        QueueList list = in(holder);
        if (list != null) {
            list.setCover(position, path);
        }
    }

    public static void drag(ViewGroup holder, boolean enabled) {
        QueueList list = in(holder);
        if (list != null) {
            list.setDragEnabled(enabled);
        }
    }

    public static void colors(ViewGroup holder, int text, int secondary, int accent, int icon) {
        QueueList list = in(holder);
        if (list != null) {
            list.setColors(text, secondary, accent, icon);
        }
    }

    public static void icons(ViewGroup holder, int handle, int menu) {
        QueueList list = in(holder);
        if (list != null) {
            list.setIcons(handle, menu);
        }
    }

    public static void scroll(ViewGroup holder, int position, int offset) {
        QueueList list = in(holder);
        if (list != null) {
            list.scrollTo(position, offset);
        }
    }

    public QueueList(Context context, Handler.Callback events) {
        super(context);
        this.events = events;
        manager = new LinearLayoutManager(context);
        setLayoutManager(manager);
        setHasFixedSize(true);
        setItemAnimator(null);
        setAdapter(adapter);
        setClipToPadding(false);
        dragger = new ItemTouchHelper(new Drag());
        dragger.attachToRecyclerView(this);
    }

    // -- data ----------------------------------------------------------------------------

    public void setRows(String[] titles, String[] artists, String[] albums, String[] times, String[] covers, int current) {
        // the same rows again (a song started, a part of the queue arrived with nothing new on screen): only the
        // playing mark moves, so the list does not rebind and blink
        if (java.util.Arrays.equals(this.titles, titles) && java.util.Arrays.equals(this.artists, artists)
                && java.util.Arrays.equals(this.albums, albums) && java.util.Arrays.equals(this.times, times)
                && java.util.Arrays.equals(this.covers, covers)) {
            if (current != this.current) {
                setCurrent(current);
            }
            return;
        }
        this.titles = titles;
        this.artists = artists;
        this.albums = albums;
        this.times = times;
        this.covers = covers;
        this.current = current;
        adapter.notifyDataSetChanged();
    }

    public void setCurrent(int position) {
        int old = current;
        current = position;
        if (old >= 0 && old < titles.length) {
            adapter.notifyItemChanged(old);
        }
        if (position >= 0 && position < titles.length) {
            adapter.notifyItemChanged(position);
        }
    }

    public void setCover(int position, String path) {
        if (position >= 0 && position < covers.length) {
            covers[position] = path;
            adapter.notifyItemChanged(position);
        }
    }

    public void removeRow(int position) {
        if (position < 0 || position >= titles.length) {
            return;
        }
        titles = without(titles, position);
        artists = without(artists, position);
        albums = without(albums, position);
        times = without(times, position);
        covers = without(covers, position);
        if (current == position) {
            current = -1;
        } else if (current > position) {
            current--;
        }
        adapter.notifyItemRemoved(position);
    }

    public void setDragEnabled(boolean enabled) {
        if (dragEnabled == enabled) {
            return;
        }
        dragEnabled = enabled;
        adapter.notifyDataSetChanged();
    }

    public void setColors(int text, int secondary, int accent, int icon) {
        textColor = text;
        secondaryColor = secondary;
        accentColor = accent;
        iconColor = icon;
        coverColor = (icon & 0x00ffffff) | 0x22000000;
        adapter.notifyDataSetChanged();
    }

    public void setIcons(int handle, int menu) {
        handleIcon = handle;
        menuIcon = menu;
        adapter.notifyDataSetChanged();
    }

    public void scrollTo(int position, int offset) {
        manager.scrollToPositionWithOffset(Math.max(0, position), offset);
    }

    // -- helpers ---------------------------------------------------------------------------

    private static String[] without(String[] items, int position) {
        String[] out = new String[items.length - 1];
        System.arraycopy(items, 0, out, 0, position);
        System.arraycopy(items, position + 1, out, position, items.length - position - 1);
        return out;
    }

    private static void move(String[] items, int from, int to) {
        String item = items[from];
        if (from < to) {
            System.arraycopy(items, from + 1, items, from, to - from);
        } else {
            System.arraycopy(items, to, items, to + 1, from - to);
        }
        items[to] = item;
    }

    private int dp(float value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics());
    }

    private void send(int what, int arg1, int arg2, Object obj) {
        if (events == null) {
            return;
        }
        Message message = Message.obtain();
        message.what = what;
        message.arg1 = arg1;
        message.arg2 = arg2;
        message.obj = obj;
        try {
            events.handleMessage(message);
        } catch (Throwable ignored) {
            // the Python side reports its own failures
        }
    }

    private void loadCover(final ImageView view, final String path) {
        if (path != null && path.equals(view.getTag()) && view.getDrawable() != null) {
            return;  // already shows this cover: a rebind leaves it be instead of clearing it first
        }
        view.setTag(path);
        if (path == null) {
            view.setImageDrawable(null);
            return;
        }
        Bitmap cached = COVERS.get(path);
        if (cached != null) {
            view.setImageBitmap(cached);
            return;
        }
        view.setImageDrawable(null);
        DECODER.execute(() -> {
            final Bitmap bitmap = BitmapFactory.decodeFile(path);
            if (bitmap == null) {
                return;
            }
            COVERS.put(path, bitmap);
            main.post(() -> {
                if (path.equals(view.getTag())) {
                    view.setImageBitmap(bitmap);
                }
            });
        });
    }

    // -- rows ------------------------------------------------------------------------------

    private class Holder extends RecyclerView.ViewHolder {
        final ImageView handle;
        final ImageView cover;
        final TextView title;
        final TextView artist;
        final TextView album;
        final TextView time;
        final ImageView menu;
        final GradientDrawable frame = new GradientDrawable();
        final GradientDrawable coverBack = new GradientDrawable();

        @SuppressLint("ClickableViewAccessibility")
        Holder(Context context) {
            super(new LinearLayout(context));
            LinearLayout row = (LinearLayout) itemView;
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(4), dp(8), dp(8), dp(8));
            row.setLayoutParams(new RecyclerView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
            frame.setCornerRadius(dp(14));
            row.setBackground(frame);

            handle = new ImageView(context);
            handle.setScaleType(ImageView.ScaleType.CENTER);
            handle.setContentDescription("Перетащить");
            handle.setOnTouchListener((v, event) -> {
                if (event.getActionMasked() == MotionEvent.ACTION_DOWN && dragEnabled) {
                    dragger.startDrag(Holder.this);
                }
                return false;
            });
            row.addView(handle, new LinearLayout.LayoutParams(dp(40), dp(48)));

            cover = new ImageView(context);
            cover.setScaleType(ImageView.ScaleType.CENTER_CROP);
            coverBack.setCornerRadius(dp(8));
            cover.setBackground(coverBack);
            cover.setOutlineProvider(new ViewOutlineProvider() {
                @Override
                public void getOutline(View view, Outline outline) {
                    outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), dp(8));
                }
            });
            cover.setClipToOutline(true);
            LinearLayout.LayoutParams coverParams = new LinearLayout.LayoutParams(dp(56), dp(56));
            coverParams.rightMargin = dp(12);
            row.addView(cover, coverParams);

            FrameLayout middle = new FrameLayout(context);
            LinearLayout texts = new LinearLayout(context);
            texts.setOrientation(LinearLayout.VERTICAL);
            title = line(context, 16);
            artist = line(context, 13);
            album = line(context, 13);
            texts.addView(title);
            texts.addView(artist);
            texts.addView(album);
            middle.addView(texts, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL));
            time = line(context, 13);
            time.setGravity(Gravity.END);
            FrameLayout.LayoutParams timeParams = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM | Gravity.END);
            middle.addView(time, timeParams);
            row.addView(middle, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

            menu = new ImageView(context);
            menu.setScaleType(ImageView.ScaleType.CENTER);
            menu.setContentDescription("Меню песни");
            menu.setOnClickListener(v -> {
                int position = getAdapterPosition();
                if (position >= 0) {
                    send(MENU, position, 0, v);
                }
            });
            row.addView(menu, new LinearLayout.LayoutParams(dp(44), dp(48)));

            row.setOnClickListener(v -> {
                int position = getAdapterPosition();
                if (position >= 0) {
                    send(ROW, position, 0, null);
                }
            });
        }

        private TextView line(Context context, int size) {
            TextView view = new TextView(context);
            view.setTextSize(TypedValue.COMPLEX_UNIT_DIP, size);
            view.setSingleLine(true);
            view.setEllipsize(TextUtils.TruncateAt.END);
            return view;
        }

        void bind(int position) {
            boolean playing = position == current;
            title.setText(titles[position]);
            artist.setText(artists[position]);
            album.setText(albums[position]);
            album.setVisibility(TextUtils.isEmpty(albums[position]) ? View.GONE : View.VISIBLE);
            time.setText(times[position]);
            // the length sits at the bottom right, so the last text line stops short of it
            int room = (int) time.getPaint().measureText(times[position] == null ? "" : times[position]) + dp(8);
            album.setPadding(0, 0, room, 0);
            if (album.getVisibility() == View.GONE) {
                artist.setPadding(0, 0, room, 0);
            } else {
                artist.setPadding(0, 0, 0, 0);
            }
            title.setTextColor(playing ? accentColor : textColor);
            artist.setTextColor(playing ? accentColor : secondaryColor);
            album.setTextColor(playing ? accentColor : secondaryColor);
            time.setTextColor(playing ? accentColor : secondaryColor);
            frame.setColor(0);
            frame.setStroke(playing ? dp(2) : 0, accentColor);
            coverBack.setColor(coverColor);
            PorterDuffColorFilter tint = new PorterDuffColorFilter(playing ? accentColor : iconColor, PorterDuff.Mode.SRC_IN);
            handle.setImageResource(handleIcon);
            handle.setColorFilter(tint);
            handle.setAlpha(dragEnabled ? 1f : 0.3f);
            menu.setImageResource(menuIcon);
            menu.setColorFilter(tint);
            itemView.setSelected(playing);
            loadCover(cover, covers[position]);
        }
    }

    private class Rows extends RecyclerView.Adapter<Holder> {
        @Override
        public Holder onCreateViewHolder(ViewGroup parent, int type) {
            return new Holder(parent.getContext());
        }

        @Override
        public void onBindViewHolder(Holder holder, int position) {
            holder.bind(position);
        }

        @Override
        public int getItemCount() {
            return titles.length;
        }
    }

    private class Drag extends ItemTouchHelper.Callback {
        @Override
        public int getMovementFlags(RecyclerView recyclerView, RecyclerView.ViewHolder viewHolder) {
            return makeMovementFlags(dragEnabled ? 3 : 0, 0);  // up and down
        }

        @Override
        public boolean isLongPressDragEnabled() {
            return false;  // only the handle starts a drag, so a long press stays free
        }

        @Override
        public boolean isItemViewSwipeEnabled() {
            return false;
        }

        @Override
        public boolean onMove(RecyclerView recyclerView, RecyclerView.ViewHolder from, RecyclerView.ViewHolder to) {
            int a = from.getAdapterPosition();
            int b = to.getAdapterPosition();
            if (a < 0 || b < 0) {
                return false;
            }
            if (dragFrom < 0) {
                dragFrom = a;
            }
            dragTo = b;
            move(titles, a, b);
            move(artists, a, b);
            move(albums, a, b);
            move(times, a, b);
            move(covers, a, b);
            if (current == a) {
                current = b;
            } else if (a < current && current <= b) {
                current--;
            } else if (b <= current && current < a) {
                current++;
            }
            adapter.notifyItemMoved(a, b);
            return true;
        }

        @Override
        public void onSwiped(RecyclerView.ViewHolder viewHolder, int direction) {
        }

        @Override
        public void clearView(RecyclerView recyclerView, RecyclerView.ViewHolder viewHolder) {
            super.clearView(recyclerView, viewHolder);
            if (dragFrom >= 0 && dragTo >= 0 && dragFrom != dragTo) {
                send(MOVED, dragFrom, dragTo, null);
            }
            dragFrom = -1;
            dragTo = -1;
        }
    }
}
