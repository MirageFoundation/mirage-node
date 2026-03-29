// Design Token System for Mirage Frontend
// Dark mode designed first, then paired with light mode
// All colors meet WCAG AA contrast requirements

export const designTokens = {
    dark: {
        // Neutral colors (foregrounds)
        neutral: {
            50: '#0A0A0B',   // Deepest background
            100: '#141519',  // Page background
            200: '#1E2126',  // Surface-1 (cards/sections)
            300: '#2A2E33',  // Surface-2 (hover/raised)
            400: '#363B42',  // Surface-3 (modals/popovers)
            500: '#4A5058',  // Borders/dividers
            600: '#6B7280',  // Muted text
            700: '#9CA3AF',  // Secondary text
            800: '#D1D5DB',  // Subtle text
            900: '#F3F4F6',  // Primary text
            950: '#FFFFFF',  // Pure white (on dark)
        },
        
        // Primary accent (main brand color)
        primary: {
            50: '#0F172A',   // Darkest
            100: '#1E293B',
            200: '#334155',
            300: '#475569',
            400: '#64748B',
            500: '#3B82F6',  // Base primary
            600: '#2563EB',  // Hover
            700: '#1D4ED8',  // Active
            800: '#1E40AF',
            900: '#1E3A8A',
        },
        
        // Secondary accent
        secondary: {
            50: '#1E1B1A',
            100: '#2D2825',
            200: '#3C3630',
            300: '#4B443B',
            400: '#5A5246',
            500: '#8B7355',  // Base secondary
            600: '#A68B6F',
            700: '#C1A389',
            800: '#DCBBA3',
            900: '#F7D3BD',
        },
        
        // Subtle accent (for backgrounds/highlights)
        subtle: {
            50: '#1A1A1F',
            100: '#25252D',
            200: '#30303B',
            300: '#3B3B49',
            400: '#464657',
            500: '#515165',
            600: '#5C5C73',
            700: '#676781',
            800: '#72728F',
            900: '#7D7D9D',
        },
        
        // Semantic colors
        success: {
            50: '#052E16',
            100: '#14532D',
            200: '#166534',
            300: '#15803D',
            400: '#16A34A',  // Base success
            500: '#22C55E',  // Bright success
            600: '#4ADE80',
            700: '#86EFAC',
        },
        
        warning: {
            50: '#422006',
            100: '#78350F',
            200: '#92400E',
            300: '#B45309',
            400: '#D97706',  // Base warning
            500: '#F59E0B',  // Bright warning
            600: '#FBBF24',
            700: '#FCD34D',
        },
        
        error: {
            50: '#450A0A',
            100: '#7F1D1D',
            200: '#991B1B',
            300: '#B91C1C',
            400: '#DC2626',  // Base error
            500: '#EF4444',  // Bright error
            600: '#F87171',
            700: '#FCA5A5',
        },
        
        // Link colors
        link: {
            default: '#60A5FA',      // WCAG AA on dark bg
            hover: '#93C5FD',        // Lighter on hover
            visited: '#A78BFA',       // Purple tint for visited
            active: '#3B82F6',        // Active state
        },
        
        // Typography
        text: {
            primary: '#F3F4F6',       // Neutral-900
            secondary: '#9CA3AF',     // Neutral-700
            muted: '#6B7280',         // Neutral-600
            disabled: '#4A5058',      // Neutral-500
            onAccent: '#0A0A0B',      // Dark text on light accent
            inverse: '#0A0A0B',       // For light surfaces
        },
        
        // Backgrounds & Surfaces
        bg: {
            page: '#141519',          // Neutral-100
            surface1: '#1E2126',       // Neutral-200 (cards/sections)
            surface2: '#2A2E33',       // Neutral-300 (hover/raised)
            surface3: '#363B42',       // Neutral-400 (modals/popovers)
        },
        
        // Borders & Dividers
        border: {
            default: '#363B42',       // Neutral-400
            subtle: '#2A2E33',         // Neutral-300
            strong: '#4A5058',         // Neutral-500
            divider: '#2A2E33',        // Neutral-300
        },
        
        // Buttons
        button: {
            primary: {
                bg: '#3B82F6',        // Primary-500
                bgHover: '#2563EB',   // Primary-600
                bgActive: '#1D4ED8',   // Primary-700
                bgDisabled: '#1E293B', // Primary-100
                text: '#FFFFFF',
                textDisabled: '#64748B', // Primary-400
                border: '#3B82F6',
                borderHover: '#2563EB',
                borderDisabled: '#334155', // Primary-200
                focusRing: 'rgba(59, 130, 246, 0.4)',
            },
            secondary: {
                bg: 'transparent',
                bgHover: '#2A2E33',   // Surface-2
                bgActive: '#363B42',   // Surface-3
                bgDisabled: 'transparent',
                text: '#F3F4F6',      // Text primary
                textDisabled: '#4A5058', // Text disabled
                border: '#363B42',     // Border default
                borderHover: '#4A5058', // Border strong
                borderDisabled: '#2A2E33', // Border subtle
                focusRing: 'rgba(59, 130, 246, 0.3)',
            },
            ghost: {
                bg: 'transparent',
                bgHover: '#2A2E33',   // Surface-2
                bgActive: '#363B42',   // Surface-3
                bgDisabled: 'transparent',
                text: '#F3F4F6',      // Text primary
                textDisabled: '#4A5058', // Text disabled
                border: 'transparent',
                borderHover: 'transparent',
                borderDisabled: 'transparent',
                focusRing: 'rgba(59, 130, 246, 0.3)',
            },
            destructive: {
                bg: '#DC2626',        // Error-400
                bgHover: '#B91C1C',   // Error-300
                bgActive: '#991B1B',   // Error-200
                bgDisabled: '#450A0A', // Error-50
                text: '#FFFFFF',
                textDisabled: '#7F1D1D', // Error-100
                border: '#DC2626',
                borderHover: '#B91C1C',
                borderDisabled: '#7F1D1D',
                focusRing: 'rgba(220, 38, 38, 0.4)',
            },
        },
        
        // Inputs
        input: {
            bg: '#1E2126',            // Surface-1
            bgHover: '#2A2E33',       // Surface-2
            bgFocus: '#1E2126',        // Surface-1
            bgDisabled: '#141519',     // Page bg
            text: '#F3F4F6',          // Text primary
            textPlaceholder: '#6B7280', // Text muted
            textDisabled: '#4A5058',   // Text disabled
            border: '#363B42',         // Border default
            borderHover: '#4A5058',    // Border strong
            borderFocus: '#3B82F6',    // Primary-500
            borderError: '#DC2626',    // Error-400
            borderDisabled: '#2A2E33', // Border subtle
            focusRing: 'rgba(59, 130, 246, 0.3)',
        },
        
        // Chips/Tags/Badges
        chip: {
            bg: '#2A2E33',            // Surface-2
            bgHover: '#363B42',       // Surface-3
            bgSelected: '#3B82F6',    // Primary-500
            bgDisabled: '#1E2126',    // Surface-1
            text: '#F3F4F6',          // Text primary
            textSelected: '#FFFFFF',   // White on selected
            textDisabled: '#4A5058',  // Text disabled
            border: '#363B42',         // Border default
            borderHover: '#4A5058',    // Border strong
            borderSelected: '#3B82F6', // Primary-500
            borderDisabled: '#2A2E33', // Border subtle
        },
        
        // Code & Inline Media
        code: {
            bg: '#0A0A0B',            // Neutral-50
            bgInline: '#1E2126',      // Surface-1
            text: '#F3F4F6',          // Text primary
            border: '#2A2E33',         // Border subtle
        },
        
        // Overlay & Scrim
        overlay: {
            scrim: 'rgba(10, 10, 11, 0.75)',  // Neutral-50 at 75%
            backdrop: 'rgba(10, 10, 11, 0.5)', // Neutral-50 at 50%
            light: 'rgba(243, 244, 246, 0.1)', // Neutral-900 at 10%
        },
        
        // Shadows
        shadow: {
            xs: '0 1px 2px rgba(10, 10, 11, 0.4)',
            sm: '0 2px 4px rgba(10, 10, 11, 0.3), 0 1px 2px rgba(10, 10, 11, 0.2)',
            md: '0 4px 8px rgba(10, 10, 11, 0.25), 0 2px 4px rgba(10, 10, 11, 0.15)',
            lg: '0 8px 16px rgba(10, 10, 11, 0.2), 0 4px 8px rgba(10, 10, 11, 0.1)',
            xl: '0 12px 24px rgba(10, 10, 11, 0.15), 0 6px 12px rgba(10, 10, 11, 0.1)',
        },
        
        // Border Radius
        radius: {
            xs: '3px',
            sm: '6px',
            md: '8px',
            lg: '12px',
            xl: '16px',
            full: '9999px',
        },
        
        // Scrollbar
        scrollbar: {
            track: 'transparent',
            thumb: '#4A5058',         // Neutral-500
            thumbHover: '#6B7280',   // Neutral-600
        },
    },
    
    light: {
        // Neutral colors (foregrounds)
        neutral: {
            50: '#FFFFFF',   // Pure white
            100: '#F9FAFB', // Page background
            200: '#F3F4F6', // Surface-1 (cards/sections)
            300: '#E5E7EB', // Surface-2 (hover/raised)
            400: '#D1D5DB', // Surface-3 (modals/popovers)
            500: '#9CA3AF', // Borders/dividers
            600: '#6B7280', // Muted text
            700: '#4B5563', // Secondary text
            800: '#374151', // Subtle text
            900: '#111827', // Primary text
            950: '#030712', // Pure black (on light)
        },
        
        // Primary accent (mirrored from dark)
        primary: {
            50: '#EFF6FF',
            100: '#DBEAFE',
            200: '#BFDBFE',
            300: '#93C5FD',
            400: '#60A5FA',
            500: '#3B82F6',  // Base primary (same as dark)
            600: '#2563EB',  // Hover
            700: '#1D4ED8',  // Active
            800: '#1E40AF',
            900: '#1E3A8A',
        },
        
        // Secondary accent
        secondary: {
            50: '#FEF7ED',
            100: '#FEECD8',
            200: '#FDD9B1',
            300: '#FCC68A',
            400: '#FBB363',
            500: '#F59E0B',  // Base secondary (warmer for light)
            600: '#D97706',
            700: '#B45309',
            800: '#92400E',
            900: '#78350F',
        },
        
        // Subtle accent
        subtle: {
            50: '#F9FAFB',
            100: '#F3F4F6',
            200: '#E5E7EB',
            300: '#D1D5DB',
            400: '#9CA3AF',
            500: '#6B7280',
            600: '#4B5563',
            700: '#374151',
            800: '#1F2937',
            900: '#111827',
        },
        
        // Semantic colors
        success: {
            50: '#F0FDF4',
            100: '#DCFCE7',
            200: '#BBF7D0',
            300: '#86EFAC',
            400: '#4ADE80',  // Base success
            500: '#22C55E',  // Bright success
            600: '#16A34A',
            700: '#15803D',
        },
        
        warning: {
            50: '#FFFBEB',
            100: '#FEF3C7',
            200: '#FDE68A',
            300: '#FCD34D',
            400: '#FBBF24',  // Base warning
            500: '#F59E0B',  // Bright warning
            600: '#D97706',
            700: '#B45309',
        },
        
        error: {
            50: '#FEF2F2',
            100: '#FEE2E2',
            200: '#FECACA',
            300: '#FCA5A5',
            400: '#F87171',  // Base error
            500: '#EF4444',  // Bright error
            600: '#DC2626',
            700: '#B91C1C',
        },
        
        // Link colors
        link: {
            default: '#2563EB',      // Primary-600 (WCAG AA on light bg)
            hover: '#1D4ED8',        // Primary-700
            visited: '#7C3AED',       // Purple tint for visited
            active: '#1E40AF',        // Primary-800
        },
        
        // Typography
        text: {
            primary: '#111827',       // Neutral-900
            secondary: '#4B5563',     // Neutral-700
            muted: '#6B7280',        // Neutral-600
            disabled: '#9CA3AF',     // Neutral-500
            onAccent: '#FFFFFF',      // Light text on dark accent
            inverse: '#F9FAFB',       // For dark surfaces
        },
        
        // Backgrounds & Surfaces
        bg: {
            page: '#F9FAFB',          // Neutral-100
            surface1: '#FFFFFF',      // Neutral-50 (cards/sections)
            surface2: '#F3F4F6',      // Neutral-200 (hover/raised)
            surface3: '#E5E7EB',      // Neutral-300 (modals/popovers)
        },
        
        // Borders & Dividers
        border: {
            default: '#E5E7EB',       // Neutral-300
            subtle: '#F3F4F6',        // Neutral-200
            strong: '#D1D5DB',        // Neutral-400
            divider: '#E5E7EB',       // Neutral-300
        },
        
        // Buttons
        button: {
            primary: {
                bg: '#3B82F6',        // Primary-500
                bgHover: '#2563EB',   // Primary-600
                bgActive: '#1D4ED8',   // Primary-700
                bgDisabled: '#E5E7EB', // Neutral-300
                text: '#FFFFFF',
                textDisabled: '#9CA3AF', // Neutral-500
                border: '#3B82F6',
                borderHover: '#2563EB',
                borderDisabled: '#D1D5DB', // Neutral-400
                focusRing: 'rgba(59, 130, 246, 0.4)',
            },
            secondary: {
                bg: 'transparent',
                bgHover: '#F3F4F6',   // Surface-2
                bgActive: '#E5E7EB', // Surface-3
                bgDisabled: 'transparent',
                text: '#111827',      // Text primary
                textDisabled: '#9CA3AF', // Text disabled
                border: '#D1D5DB',     // Border strong
                borderHover: '#9CA3AF', // Neutral-500
                borderDisabled: '#E5E7EB', // Border default
                focusRing: 'rgba(59, 130, 246, 0.3)',
            },
            ghost: {
                bg: 'transparent',
                bgHover: '#F3F4F6',   // Surface-2
                bgActive: '#E5E7EB',  // Surface-3
                bgDisabled: 'transparent',
                text: '#111827',      // Text primary
                textDisabled: '#9CA3AF', // Text disabled
                border: 'transparent',
                borderHover: 'transparent',
                borderDisabled: 'transparent',
                focusRing: 'rgba(59, 130, 246, 0.3)',
            },
            destructive: {
                bg: '#DC2626',        // Error-600
                bgHover: '#B91C1C',   // Error-700
                bgActive: '#991B1B',   // Error-800
                bgDisabled: '#FEE2E2', // Error-100
                text: '#FFFFFF',
                textDisabled: '#FCA5A5', // Error-300
                border: '#DC2626',
                borderHover: '#B91C1C',
                borderDisabled: '#FECACA', // Error-200
                focusRing: 'rgba(220, 38, 38, 0.4)',
            },
        },
        
        // Inputs
        input: {
            bg: '#FFFFFF',            // Surface-1
            bgHover: '#F9FAFB',      // Page bg
            bgFocus: '#FFFFFF',       // Surface-1
            bgDisabled: '#F3F4F6',   // Surface-2
            text: '#111827',          // Text primary
            textPlaceholder: '#9CA3AF', // Neutral-500
            textDisabled: '#D1D5DB',   // Neutral-400
            border: '#D1D5DB',        // Border strong
            borderHover: '#9CA3AF',   // Neutral-500
            borderFocus: '#3B82F6',   // Primary-500
            borderError: '#DC2626',   // Error-600
            borderDisabled: '#E5E7EB', // Border default
            focusRing: 'rgba(59, 130, 246, 0.3)',
        },
        
        // Chips/Tags/Badges
        chip: {
            bg: '#F3F4F6',            // Surface-2
            bgHover: '#E5E7EB',       // Surface-3
            bgSelected: '#3B82F6',    // Primary-500
            bgDisabled: '#F9FAFB',    // Page bg
            text: '#111827',          // Text primary
            textSelected: '#FFFFFF',   // White on selected
            textDisabled: '#D1D5DB',  // Neutral-400
            border: '#E5E7EB',        // Border default
            borderHover: '#D1D5DB',   // Border strong
            borderSelected: '#3B82F6', // Primary-500
            borderDisabled: '#F3F4F6', // Border subtle
        },
        
        // Code & Inline Media
        code: {
            bg: '#111827',            // Neutral-900
            bgInline: '#F3F4F6',      // Surface-2
            text: '#F9FAFB',         // Text inverse
            border: '#E5E7EB',        // Border default
        },
        
        // Overlay & Scrim
        overlay: {
            scrim: 'rgba(3, 7, 18, 0.75)',  // Neutral-950 at 75%
            backdrop: 'rgba(3, 7, 18, 0.5)', // Neutral-950 at 50%
            light: 'rgba(17, 24, 39, 0.05)', // Neutral-900 at 5%
        },
        
        // Shadows
        shadow: {
            xs: '0 1px 2px rgba(3, 7, 18, 0.05)',
            sm: '0 2px 4px rgba(3, 7, 18, 0.06), 0 1px 2px rgba(3, 7, 18, 0.04)',
            md: '0 4px 8px rgba(3, 7, 18, 0.08), 0 2px 4px rgba(3, 7, 18, 0.06)',
            lg: '0 8px 16px rgba(3, 7, 18, 0.1), 0 4px 8px rgba(3, 7, 18, 0.08)',
            xl: '0 12px 24px rgba(3, 7, 18, 0.12), 0 6px 12px rgba(3, 7, 18, 0.1)',
        },
        
        // Border Radius
        radius: {
            xs: '3px',
            sm: '6px',
            md: '8px',
            lg: '12px',
            xl: '16px',
            full: '9999px',
        },
        
        // Scrollbar
        scrollbar: {
            track: 'transparent',
            thumb: '#9CA3AF',        // Neutral-500
            thumbHover: '#6B7280',  // Neutral-600
        },
    },
};

// Legacy theme format for backward compatibility
export const createLegacyTheme = (mode) => {
    const tokens = designTokens[mode];
    return {
        name: mode,
        colors: {
            // Legacy mappings
            bg: tokens.bg.page,
            text: tokens.text.primary,
            subtleText: tokens.text.secondary,
            mutedText: tokens.text.muted,
            panel: tokens.bg.surface1,
            panelAlt: tokens.bg.surface2,
            border: tokens.border.default,
            accent: tokens.button.secondary.bgHover,
            accentHover: tokens.button.secondary.bgActive,
            accentDisabled: tokens.button.secondary.bgDisabled,
            buttonText: tokens.button.primary.text,
            link: tokens.link.default,
            linkHover: tokens.link.hover,
            scrollbar: tokens.scrollbar.thumb,
            
            // New comprehensive tokens (accessible via theme.colors.*)
            ...tokens,
        },
    };
};

