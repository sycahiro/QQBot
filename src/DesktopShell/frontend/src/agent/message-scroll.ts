type Row = { id: string; top: number; bottom: number };
export type MessageMetrics = { top: number; height: number; total: number; rows: Row[] };

/** Keep a visible message anchored while animated rows grow or old pages prepend. */
export class MessageScroll {
    private initialized = false;
    private following: boolean;
    private anchors: Row[] = [];
    private readonly allowFollow: boolean;
    constructor(allowFollow = true) {
        this.allowFollow = allowFollow;
        this.following = allowFollow;
    }
    remember(view: MessageMetrics) {
        this.anchors = view.rows.filter((row) => row.bottom > 0 && row.top < view.height);
    }
    scrolled(view: MessageMetrics) {
        if (!this.initialized) return;
        this.following = this.allowFollow && view.total - view.top - view.height <= 40;
        this.remember(view);
    }
    pause(view: MessageMetrics) {
        this.following = false;
        this.remember(view);
    }
    latest() {
        this.following = this.allowFollow;
        this.anchors = [];
    }
    position(view: MessageMetrics, loaded: boolean): number | null {
        if (!this.initialized) {
            if (!loaded) return null;
            this.initialized = true;
            return this.following ? view.total : 0;
        }
        if (this.following) return view.total;
        for (const anchor of this.anchors) {
            const row = view.rows.find((row) => row.id === anchor.id);
            if (row) return view.top + row.top - anchor.top;
        }
        return null;
    }
}
