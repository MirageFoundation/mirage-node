import { usePostCurateActions } from '../../../logic/usePostCurateActions';

/**
 * Curate action rows for the post Mod (shield) menu.
 *
 * Pass `active` when the menu is open so hide/show state is loaded then.
 * Callers supply `renderItem(item)`. No section headers.
 */
export default function CurateMenuItems({ post, onDone, renderItem, active = false }) {
    const { visible, items, loading, modError } = usePostCurateActions(post, { active });
    if (!visible || typeof renderItem !== 'function') return null;
    if (!active) return null;
    if (loading && items.length === 0) return null;
    if (modError && items.length === 0) {
        console.error('[curation] curate menu blocked by mod state error', { error: modError });
        return null;
    }

    return (
        <>
            {items.map((item) => renderItem({
                ...item,
                onClick: (event) => {
                    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
                    if (event && typeof event.preventDefault === 'function') event.preventDefault();
                    item.run();
                    if (typeof onDone === 'function') onDone();
                },
            }))}
        </>
    );
}
