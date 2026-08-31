import { usePostCurateActions } from '../../../logic/usePostCurateActions';

/**
 * Pass `active` when the menu is open so hide/show state is loaded then.
 * Callers supply `renderItem(item)`. No section headers.
 */
export default function CurateMenuItems({ post, onDone, renderItem, active = false, updatePost }) {
    const { visible, items, loading, modError } = usePostCurateActions(post, { active, updatePost });
    if (!visible || typeof renderItem !== 'function') return null;
    if (!active) return null;
    if (loading && items.length === 0) return null;
    if (modError && items.length === 0) {
        console.error('[curation] curate menu blocked by mod state error', { error: modError });
        return null;
    }

    return (
        <>
            {items.map((item) => renderItem(typeof item.run !== 'function' ? item : {
                ...item,
                onClick: (event) => {
                    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
                    if (event && typeof event.preventDefault === 'function') event.preventDefault();
                    console.debug('[curation] curate menu item', { key: item.key });
                    item.run();
                    // Close after this click finishes so a unmount mid-click cannot
                    // retarget onto Back / Home underneath the menu.
                    if (typeof onDone === 'function') {
                        window.setTimeout(() => onDone(), 0);
                    }
                },
            }))}
        </>
    );
}
