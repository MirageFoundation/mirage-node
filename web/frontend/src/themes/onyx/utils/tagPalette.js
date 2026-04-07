export const getTagPalette = (theme, tag) => {
    switch (tag) {
        case 'adult':
            return {
                bg: theme.colors.warningBg,
                border: theme.colors.warningBorder,
                text: theme.colors.warning,
            };
        case 'violence':
        case 'gore':
        case 'death':
            return {
                bg: theme.colors.dangerBg,
                border: theme.colors.dangerBorder,
                text: theme.colors.danger,
            };
        case 'sensitive':
            return {
                bg: theme.colors.accentSubtle,
                border: theme.colors.borderStrong,
                text: theme.colors.text,
            };
        default: {
            console.debug('[Onyx][TagBadge] Unknown content tag', tag);
            throw new Error(`Unknown content tag: ${tag}`);
        }
    }
};
