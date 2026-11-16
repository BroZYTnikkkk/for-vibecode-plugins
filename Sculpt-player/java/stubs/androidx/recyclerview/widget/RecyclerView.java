package androidx.recyclerview.widget;

import android.content.Context;
import android.view.View;
import android.view.ViewGroup;

/** Compile-time stand-in for the app's own copy of RecyclerView: only the members sculpt.QueueList uses. */
public class RecyclerView extends ViewGroup {
    public RecyclerView(Context context) {
        super(context);
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
    }

    public void setAdapter(Adapter adapter) {
    }

    public void setLayoutManager(LayoutManager layoutManager) {
    }

    public void setItemAnimator(ItemAnimator itemAnimator) {
    }

    public void setHasFixedSize(boolean fixed) {
    }

    public void scrollToPosition(int position) {
    }

    public static abstract class ItemAnimator {
    }

    public static class LayoutParams extends ViewGroup.MarginLayoutParams {
        public LayoutParams(int width, int height) {
            super(width, height);
        }
    }

    public static abstract class LayoutManager {
    }

    public static abstract class ViewHolder {
        public final View itemView;

        public ViewHolder(View view) {
            itemView = view;
        }

        public final int getAdapterPosition() {
            return 0;
        }
    }

    public static abstract class Adapter<VH extends ViewHolder> {
        public abstract VH onCreateViewHolder(ViewGroup parent, int type);

        public abstract void onBindViewHolder(VH holder, int position);

        public abstract int getItemCount();

        public void notifyDataSetChanged() {
        }

        public void notifyItemChanged(int position) {
        }

        public void notifyItemMoved(int from, int to) {
        }

        public void notifyItemRemoved(int position) {
        }
    }
}
