package androidx.recyclerview.widget;

/** Compile-time stand-in for the app's ItemTouchHelper. */
public class ItemTouchHelper {
    public ItemTouchHelper(Callback callback) {
    }

    public void attachToRecyclerView(RecyclerView recyclerView) {
    }

    public void startDrag(RecyclerView.ViewHolder viewHolder) {
    }

    public static abstract class Callback {
        public static int makeMovementFlags(int dragFlags, int swipeFlags) {
            return 0;
        }

        public abstract int getMovementFlags(RecyclerView recyclerView, RecyclerView.ViewHolder viewHolder);

        public abstract boolean onMove(RecyclerView recyclerView, RecyclerView.ViewHolder from, RecyclerView.ViewHolder to);

        public abstract void onSwiped(RecyclerView.ViewHolder viewHolder, int direction);

        public boolean isLongPressDragEnabled() {
            return true;
        }

        public boolean isItemViewSwipeEnabled() {
            return true;
        }

        public void clearView(RecyclerView recyclerView, RecyclerView.ViewHolder viewHolder) {
        }

        public void onSelectedChanged(RecyclerView.ViewHolder viewHolder, int actionState) {
        }
    }
}
