/**
 * Format umirage amount as MIRAGE with proper formatting:
 * - Thousands separators
 * - No decimals if whole number
 * - Up to 6 decimals otherwise, trimmed trailing zeros
 */
export function formatMirage(umirage) {
    const n = Number(umirage);
    if (!isFinite(n)) return '0';
    
    const mirage = n / 1_000_000;
    
    // If it's a whole number, no decimals
    if (Number.isInteger(mirage)) {
        return mirage.toLocaleString('en-US');
    }
    
    // Otherwise, show up to 6 decimals but trim trailing zeros
    const fixed = mirage.toFixed(6);
    const [intPart, decPart] = fixed.split('.');
    const trimmedDec = decPart.replace(/0+$/, '');
    
    const formattedInt = Number(intPart).toLocaleString('en-US');
    
    if (trimmedDec === '') {
        return formattedInt;
    }
    
    return `${formattedInt}.${trimmedDec}`;
}

/**
 * Format umirage amount as compact MIRAGE (e.g., 100k, 1.5M, 2B)
 * - Uses k/M/B suffixes for large numbers
 * - Shows up to 1 decimal place when needed
 */
export function formatMirageCompact(umirage) {
    const n = Number(umirage);
    if (!isFinite(n)) return '0';
    
    const mirage = n / 1_000_000;
    
    if (mirage === 0) return '0';
    
    if (mirage >= 1_000_000_000) {
        const v = mirage / 1_000_000_000;
        return v % 1 === 0 ? `${v}B` : `${v.toFixed(1)}B`;
    }
    if (mirage >= 1_000_000) {
        const v = mirage / 1_000_000;
        return v % 1 === 0 ? `${v}M` : `${v.toFixed(1)}M`;
    }
    if (mirage >= 1_000) {
        const v = mirage / 1_000;
        return v % 1 === 0 ? `${v}k` : `${v.toFixed(1)}k`;
    }
    
    // Small values: show up to 2 decimals if needed
    if (Number.isInteger(mirage)) {
        return String(mirage);
    }
    return mirage.toFixed(2).replace(/\.?0+$/, '');
}
