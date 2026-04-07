export const resolveCardSize = (value) => {
    if (value === 'compact' || value === 'media') {
        return value;
    }
    console.debug('[Onyx][CardSize] Unsupported card size', value);
    throw new Error(`Unsupported card size: ${value}`);
};
