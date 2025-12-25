/**
 * Mirage Design System - Comprehensive Theme Tokens
 * 
 * Design Principles:
 * - WCAG AA contrast (4.5:1 for text, 3:1 for UI elements)
 * - Dark mode first, light mode pair-mirrored
 * - Consistent brand feeling across modes
 * - No neon or overly saturated colors
 * - Balanced shadows with low blur
 */

// ============================================================================
// SPACING & RADIUS SCALE
// ============================================================================

export const radius = {
    xs: '4px',      // Small controls, tags, badges
    sm: '6px',      // Buttons, inputs, pills
    md: '10px',     // Cards, dropdowns
    lg: '14px',     // Large cards, modals
    xl: '20px',     // Hero sections, large panels
    full: '9999px', // Circular elements, fully rounded pills
};

// ============================================================================
// SHADOW SYSTEM
// ============================================================================

export const shadows = {
    dark: {
        sm: '0 2px 4px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.2)',
        md: '0 4px 12px rgba(0, 0, 0, 0.4), 0 2px 4px rgba(0, 0, 0, 0.25)',
        lg: '0 8px 24px rgba(0, 0, 0, 0.5), 0 4px 8px rgba(0, 0, 0, 0.3)',
        focus: '0 0 0 3px rgba(99, 179, 237, 0.4)',
        focusError: '0 0 0 3px rgba(239, 68, 68, 0.4)',
        focusSuccess: '0 0 0 3px rgba(34, 197, 94, 0.4)',
        overlay: 'rgba(0, 0, 0, 0.75)',
    },
    light: {
        sm: '0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06)',
        md: '0 4px 12px rgba(0, 0, 0, 0.1), 0 2px 4px rgba(0, 0, 0, 0.06)',
        lg: '0 8px 24px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.08)',
        focus: '0 0 0 3px rgba(59, 130, 246, 0.35)',
        focusError: '0 0 0 3px rgba(220, 38, 38, 0.35)',
        focusSuccess: '0 0 0 3px rgba(22, 163, 74, 0.35)',
        overlay: 'rgba(0, 0, 0, 0.5)',
    }
};

// ============================================================================
// DARK THEME - Primary theme, designed first
// ============================================================================

export const darkTheme = {
    name: 'dark',

    colors: {
        // === Background/Surface Tiers ===
        bg: '#0f1114',                    // Page background (deepest)
        surface1: '#1a1d21',              // Cards, sections (elevated)
        surface2: '#22262b',              // Hover/raised surfaces
        surface3: '#2a2f36',              // Modals, popovers (highest)

        // Legacy aliases (for backwards compatibility)
        panel: '#1a1d21',
        panelAlt: '#22262b',

        // === Border Colors ===
        border: '#32383f',                // Default border
        borderSubtle: '#282d33',          // Low-elevation borders
        borderStrong: '#434a52',          // High-emphasis borders
        borderFocus: '#63b3ed',           // Focus ring color

        // === Text Colors ===
        text: '#f0f2f5',                  // Primary text (WCAG AA on surface1: 15:1)
        textSecondary: '#a0a8b3',         // Secondary/muted text (WCAG AA: 6.5:1)
        textDisabled: '#5a6370',          // Disabled text (intentionally lower contrast)
        textOnAccent: '#0f1114',          // Text on primary buttons
        textOnAccentSubtle: '#1a1d21',    // Text on subtle accents

        // Legacy aliases
        subtleText: '#a0a8b3',
        mutedText: '#7a8390',

        // === Primary Accent ===
        accent: '#63b3ed',                // Primary accent (bright sky blue)
        accentHover: '#4299e1',           // Primary hover
        accentActive: '#3182ce',          // Primary pressed/active
        accentSubtle: 'rgba(99, 179, 237, 0.12)',  // Subtle accent background
        accentDisabled: '#4a5568',        // Disabled accent

        // === Secondary Accent ===
        secondary: '#2a2f36',             // Secondary button background
        secondaryHover: '#343b44',        // Secondary hover
        secondaryActive: '#3d454f',       // Secondary active
        secondaryBorder: '#434a52',       // Secondary border

        // === Semantic Colors ===
        success: '#48bb78',               // Success green
        successHover: '#38a169',
        successSubtle: 'rgba(72, 187, 120, 0.12)',
        successText: '#68d391',           // Success text color

        warning: '#ed8936',               // Warning orange
        warningHover: '#dd6b20',
        warningSubtle: 'rgba(237, 137, 54, 0.12)',
        warningText: '#f6ad55',           // Warning text color

        error: '#f56565',                 // Error red
        errorHover: '#e53e3e',
        errorSubtle: 'rgba(245, 101, 101, 0.12)',
        errorText: '#fc8181',             // Error text color

        // === Link Colors ===
        link: '#63b3ed',                  // Link default
        linkHover: '#90cdf4',             // Link hover
        linkVisited: '#b794f4',           // Link visited (purple tint)
        linkActive: '#4299e1',            // Link active/pressed

        // === Divider/Separator ===
        divider: '#282d33',               // Subtle dividers
        dividerStrong: '#32383f',         // Prominent dividers

        // === Chips/Tags/Badges ===
        chip: '#22262b',                  // Default chip background
        chipBorder: '#32383f',            // Chip border
        chipText: '#a0a8b3',              // Chip text
        chipHover: '#2a2f36',             // Chip hover
        chipActive: '#343b44',            // Chip active/selected
        chipActiveText: '#f0f2f5',        // Active chip text

        // === Code/Inline Media ===
        code: '#22262b',                  // Inline code background
        codeBorder: '#32383f',            // Code block border
        codeText: '#e2e8f0',              // Code text

        // === Vote Colors ===
        voteUp: '#48bb78',                // Upvote green
        voteUpHover: '#68d391',
        voteUpBg: 'rgba(72, 187, 120, 0.15)',
        voteDown: '#f56565',              // Downvote red
        voteDownHover: '#fc8181',
        voteDownBg: 'rgba(245, 101, 101, 0.15)',

        // === Overlay/Scrim ===
        overlay: 'rgba(0, 0, 0, 0.75)',
        overlayLight: 'rgba(0, 0, 0, 0.5)',

        // === Scrollbar ===
        scrollbar: '#434a52',
        scrollbarHover: '#5a6370',
        scrollbarTrack: 'transparent',

        // === Button Text (legacy) ===
        buttonText: '#0f1114',
    },

    shadows: shadows.dark,
    radius,
};

// ============================================================================
// LIGHT THEME - Pair-mirrored from dark theme
// ============================================================================

export const lightTheme = {
    name: 'light',

    colors: {
        // === Background/Surface Tiers ===
        bg: '#f8fafc',                    // Page background (lightest)
        surface1: '#ffffff',              // Cards, sections
        surface2: '#f1f5f9',              // Hover/raised surfaces
        surface3: '#e2e8f0',              // Modals, popovers

        // Legacy aliases
        panel: '#ffffff',
        panelAlt: '#f1f5f9',

        // === Border Colors ===
        border: '#d1d5db',                // Default border
        borderSubtle: '#e5e7eb',          // Low-elevation borders
        borderStrong: '#9ca3af',          // High-emphasis borders
        borderFocus: '#3b82f6',           // Focus ring color

        // === Text Colors ===
        text: '#1a202c',                  // Primary text (WCAG AA on surface1: 15.6:1)
        textSecondary: '#4a5568',         // Secondary/muted text (WCAG AA: 7.5:1)
        textDisabled: '#a0aec0',          // Disabled text
        textOnAccent: '#ffffff',          // Text on primary buttons
        textOnAccentSubtle: '#f8fafc',    // Text on subtle accents

        // Legacy aliases
        subtleText: '#4a5568',
        mutedText: '#718096',

        // === Primary Accent ===
        accent: '#3b82f6',                // Primary accent (vivid blue)
        accentHover: '#2563eb',           // Primary hover
        accentActive: '#1d4ed8',          // Primary pressed/active
        accentSubtle: 'rgba(59, 130, 246, 0.1)',   // Subtle accent background
        accentDisabled: '#cbd5e1',        // Disabled accent

        // === Secondary Accent ===
        secondary: '#f1f5f9',             // Secondary button background
        secondaryHover: '#e2e8f0',        // Secondary hover
        secondaryActive: '#cbd5e1',       // Secondary active
        secondaryBorder: '#d1d5db',       // Secondary border

        // === Semantic Colors ===
        success: '#22c55e',               // Success green
        successHover: '#16a34a',
        successSubtle: 'rgba(34, 197, 94, 0.1)',
        successText: '#15803d',           // Success text color

        warning: '#f59e0b',               // Warning orange
        warningHover: '#d97706',
        warningSubtle: 'rgba(245, 158, 11, 0.1)',
        warningText: '#b45309',           // Warning text color

        error: '#ef4444',                 // Error red
        errorHover: '#dc2626',
        errorSubtle: 'rgba(239, 68, 68, 0.1)',
        errorText: '#dc2626',             // Error text color

        // === Link Colors ===
        link: '#2563eb',                  // Link default
        linkHover: '#1d4ed8',             // Link hover
        linkVisited: '#7c3aed',           // Link visited (purple)
        linkActive: '#1e40af',            // Link active/pressed

        // === Divider/Separator ===
        divider: '#e5e7eb',               // Subtle dividers
        dividerStrong: '#d1d5db',         // Prominent dividers

        // === Chips/Tags/Badges ===
        chip: '#f1f5f9',                  // Default chip background
        chipBorder: '#d1d5db',            // Chip border
        chipText: '#4a5568',              // Chip text
        chipHover: '#e2e8f0',             // Chip hover
        chipActive: '#3b82f6',            // Chip active/selected
        chipActiveText: '#ffffff',        // Active chip text

        // === Code/Inline Media ===
        code: '#f1f5f9',                  // Inline code background
        codeBorder: '#e2e8f0',            // Code block border
        codeText: '#1a202c',              // Code text

        // === Vote Colors ===
        voteUp: '#16a34a',                // Upvote green
        voteUpHover: '#15803d',
        voteUpBg: 'rgba(22, 163, 74, 0.1)',
        voteDown: '#dc2626',              // Downvote red
        voteDownHover: '#b91c1c',
        voteDownBg: 'rgba(220, 38, 38, 0.1)',

        // === Overlay/Scrim ===
        overlay: 'rgba(0, 0, 0, 0.5)',
        overlayLight: 'rgba(0, 0, 0, 0.3)',

        // === Scrollbar ===
        scrollbar: '#9ca3af',
        scrollbarHover: '#6b7280',
        scrollbarTrack: 'transparent',

        // === Button Text (legacy) ===
        buttonText: '#1a202c',
    },

    shadows: shadows.light,
    radius,
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Get theme by name
 */
export function getTheme(themeName) {
    return themeName === 'light' ? lightTheme : darkTheme;
}

/**
 * Calculate system theme preference
 */
export function getSystemTheme() {
    if (typeof window === 'undefined') return 'dark';
    try {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch (_) {
        return 'dark';
    }
}

// ============================================================================
// CSS CUSTOM PROPERTIES (for potential future CSS variables approach)
// ============================================================================

export function generateCSSVariables(theme) {
    const vars = {};
    const flatten = (obj, prefix = '') => {
        for (const [key, value] of Object.entries(obj)) {
            const varName = prefix ? `${prefix}-${key}` : key;
            if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
                flatten(value, varName);
            } else {
                vars[`--${varName}`] = value;
            }
        }
    };
    flatten(theme.colors, 'color');
    flatten(theme.shadows, 'shadow');
    flatten(theme.radius, 'radius');
    return vars;
}

export default { darkTheme, lightTheme, shadows, radius };

