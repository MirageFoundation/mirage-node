import styled from 'styled-components';
import { usePostCurateActions } from '../../../logic/usePostCurateActions';
import { requireThemeColor } from '../../../utils/themeColor';

const DefaultHeader = styled.div`
    padding: 10px 14px;
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1;
    color: ${({ theme }) => requireThemeColor(theme, 'menuHeaderText')};
    white-space: nowrap;
`;

/**
 * Shared Curate section for the post Mod (shield) menu.
 *
 * Callers supply `renderItem(item)` so ModMenuChip can keep its own menu
 * row components. Optional `renderHeader`.
 */
export default function CurateMenuItems({ post, onDone, renderItem, renderHeader }) {
    const { visible, items, teamName } = usePostCurateActions(post);
    if (!visible || typeof renderItem !== 'function') return null;

    const headerLabel = teamName ? `Curate · ${teamName}` : 'Curate';
    const header = typeof renderHeader === 'function'
        ? renderHeader(headerLabel)
        : <DefaultHeader>{headerLabel}</DefaultHeader>;

    return (
        <>
            {header}
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
