import React from 'react';
import styled, { css, keyframes } from 'styled-components';
import { Link } from 'react-router-dom';

/**
 * mirageapp Button — R1–R7 compliant.
 *
 * Variants:
 *   primary       — filled brand pill (`followBtnBg`)
 *   primaryDanger — filled danger pill (`voteDown` / danger tokens)
 *   secondary     — outlined panel pill
 *   danger        — tinted danger pill (`buttonDanger*`)
 *   success       — tinted success pill (`buttonSuccess*`)
 *   warning       — tinted warning pill (uses danger tokens — warning is visually danger-ish)
 *   ghost         — transparent pill → `hoverBg` on hover (default for Cancel / neutral)
 *   subtle        — subtle tinted pill (Following-style, uses `accent` + `border`)
 *   link          — inline text link
 *
 * Sizes: xs / sm / md / lg / pill. All use R7 typography (0.65–0.9rem, weight 500/600).
 * Focus: R5 — neutral `borderStrong`, no blue ring.
 */

const spin = keyframes`
    to { transform: rotate(360deg); }
`;

const Spinner = styled.span`
    display: inline-block;
    width: 0.85em;
    height: 0.85em;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: ${spin} 0.75s linear infinite;
    margin-right: 0.4em;
    vertical-align: middle;
`;

const MIN_WIDTH_PRESETS = {
    copy: '4.5rem',
    follow: '8.5rem',
};

/** In flat mode: `subtle` uses success tint (e.g. Following). Dismiss/neutral actions should use `ghost`, not `subtle`. */
const flatModeOverride = css`
    ${({ theme, $variant }) => theme.layout.flatMode && css`
        border-radius: ${theme.layout.buttonRadius} !important;
        box-shadow: none !important;
        transform: none !important;
        font-size: ${theme.layout.buttonSize} !important;
        padding: ${theme.layout.buttonPadding} !important;

        ${$variant === 'subtle' ? css`
            background: ${theme.colors.buttonSuccessBg} !important;
            color: ${theme.colors.text} !important;
            border: 1px solid ${theme.colors.buttonSuccessBorder} !important;
            &:hover:not(:disabled) {
                background: ${theme.colors.buttonSuccessHoverBg} !important;
                box-shadow: none !important;
                transform: none !important;
            }
        ` : $variant === 'primaryDanger' ? css`
            background: ${theme.colors.buttonDangerBg} !important;
            color: ${theme.colors.text} !important;
            border: 1px solid ${theme.colors.buttonDangerBorder} !important;
            &:hover:not(:disabled) {
                background: ${theme.colors.buttonDangerHoverBg} !important;
                box-shadow: none !important;
                transform: none !important;
            }
        ` : css`
            background: ${theme.colors.panelAlt} !important;
            color: ${theme.colors.text} !important;
            border: 1px solid ${theme.colors.border} !important;
            &:hover:not(:disabled) {
                background: ${theme.colors.accent} !important;
                box-shadow: none !important;
                transform: none !important;
            }
        `}
    `}
`;

const baseStyles = css`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    white-space: nowrap;
    border: 1px solid transparent;
    font-family: inherit;
    box-shadow: none;

    &:focus {
        outline: none;
    }

    &:focus-visible {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }

    ${({ $minWidth }) => $minWidth && css`
        min-width: ${MIN_WIDTH_PRESETS[$minWidth] || $minWidth};
    `}
`;

const getSizeStyles = (size) => {
    switch (size) {
        case 'xs':
            return css`
                padding: 0.22rem 0.55rem;
                font-size: 0.65rem;
                border-radius: 6px;
            `;
        case 'sm':
            return css`
                padding: 0.38rem 0.75rem;
                font-size: 0.72rem;
                border-radius: 6px;
            `;
        case 'lg':
            return css`
                padding: 0.55rem 1.3rem;
                font-size: 0.85rem;
                border-radius: 8px;
            `;
        case 'pill':
            return css`
                padding: 0.5rem 0.9rem;
                font-size: 0.75rem;
                border-radius: 999px;
            `;
        case 'md':
        default:
            return css`
                padding: 0.48rem 0.95rem;
                font-size: 0.78rem;
                border-radius: 8px;
            `;
    }
};

const getVariantStyles = (variant, theme) => {
    switch (variant) {
        case 'secondary':
            return css`
                background: ${theme.colors.panel};
                color: ${theme.colors.text};
                border: 1px solid ${theme.colors.border};

                &:hover:not(:disabled) {
                    background: ${theme.colors.accent};
                    border-color: ${theme.colors.borderStrong};
                }
            `;
        case 'danger':
            return css`
                background: ${theme.colors.buttonDangerBg};
                color: ${theme.colors.voteDown};
                border: 1px solid ${theme.colors.buttonDangerBorder};

                &:hover:not(:disabled) {
                    background: ${theme.colors.buttonDangerHoverBg};
                }
            `;
        case 'success':
            return css`
                background: ${theme.colors.buttonSuccessBg};
                color: ${theme.colors.voteUp};
                border: 1px solid ${theme.colors.buttonSuccessBorder};

                &:hover:not(:disabled) {
                    background: ${theme.colors.buttonSuccessHoverBg};
                }
            `;
        case 'warning':
            /* No dedicated warning token pair in R2; use danger tokens since most "warning" usages
               are confirm-destructive actions (Block user, Delete post, Suspend, Report). */
            return css`
                background: ${theme.colors.buttonDangerBg};
                color: ${theme.colors.voteDown};
                border: 1px solid ${theme.colors.buttonDangerBorder};

                &:hover:not(:disabled) {
                    background: ${theme.colors.buttonDangerHoverBg};
                }
            `;
        case 'ghost':
            return css`
                background: transparent;
                color: ${theme.colors.text};
                border: 1px solid ${theme.colors.border};

                &:hover:not(:disabled) {
                    background: ${theme.colors.hoverBg};
                    border-color: ${theme.colors.borderStrong};
                }
            `;
        case 'subtle':
            return css`
                background: ${theme.colors.accent};
                color: ${theme.colors.text};
                border: 1px solid ${theme.colors.border};

                &:hover:not(:disabled) {
                    background: ${theme.colors.accentHover};
                    border-color: ${theme.colors.borderStrong};
                }
            `;
        case 'link':
            return css`
                background: transparent;
                color: ${theme.colors.link};
                border: none;
                padding: 0;
                font-weight: 500;

                &:hover:not(:disabled) {
                    color: ${theme.colors.linkHover};
                    text-decoration: underline;
                }
            `;
        case 'primaryDanger':
            return css`
                background: ${theme.colors.voteDown};
                color: #ffffff;
                border: 1px solid ${theme.colors.voteDown};

                &:hover:not(:disabled) {
                    background: ${theme.colors.voteDownHover};
                    border-color: ${theme.colors.voteDownHover};
                }
            `;
        case 'primary':
        default:
            return css`
                background: ${theme.colors.followBtnBg};
                color: #ffffff;
                border: 1px solid ${theme.colors.followBtnBg};

                &:hover:not(:disabled) {
                    background: ${theme.colors.followBtnBgHover};
                    border-color: ${theme.colors.followBtnBgHover};
                }
            `;
    }
};

const getMobileSizeStyles = (size, variant) => {
    if (variant === 'link') {
        return css``;
    }
    switch (size) {
        case 'xs':
            return css`
                padding: 0.18rem 0.5rem;
                font-size: 0.6rem;
                border-radius: 6px;
            `;
        case 'sm':
            return css`
                padding: 0.34rem 0.6rem;
                font-size: 0.7rem;
                border-radius: 6px;
            `;
        case 'lg':
            return css`
                padding: 0.48rem 1.1rem;
                font-size: 0.8rem;
                border-radius: 8px;
            `;
        case 'pill':
            return css`
                padding: 0.42rem 0.75rem;
                font-size: 0.72rem;
                border-radius: 999px;
            `;
        case 'md':
        default:
            return css`
                padding: 0.42rem 0.85rem;
                font-size: 0.75rem;
                border-radius: 8px;
            `;
    }
};

const copiedStyles = css`
    background: ${({ theme }) => theme.colors.buttonSuccessBg} !important;
    color: ${({ theme }) => theme.colors.voteUp} !important;
    border-color: ${({ theme }) => theme.colors.buttonSuccessBorder} !important;
`;

const StyledButton = styled.button`
    ${baseStyles}
    ${({ $size }) => getSizeStyles($size)}
    ${({ $variant, theme }) => getVariantStyles($variant, theme)}
    ${({ $fullWidth }) => $fullWidth && css`width: 100%;`}
    ${({ $copied }) => $copied && copiedStyles}
    ${flatModeOverride}

    @media (max-width: 600px) {
        ${({ $size, $variant }) => getMobileSizeStyles($size, $variant)}
        ${({ $mobileFullWidth }) => $mobileFullWidth && css`
            width: 100%;
            text-align: center;
        `}
    }
`;

const StyledLink = styled(Link)`
    ${baseStyles}
    ${({ $size }) => getSizeStyles($size)}
    ${({ $variant, theme }) => getVariantStyles($variant, theme)}
    ${({ $fullWidth }) => $fullWidth && css`width: 100%;`}
    ${flatModeOverride}

    @media (max-width: 600px) {
        ${({ $size, $variant }) => getMobileSizeStyles($size, $variant)}
        ${({ $mobileFullWidth }) => $mobileFullWidth && css`
            width: 100%;
            text-align: center;
        `}
    }
`;

const StyledAnchor = styled.a`
    ${baseStyles}
    ${({ $size }) => getSizeStyles($size)}
    ${({ $variant, theme }) => getVariantStyles($variant, theme)}
    ${({ $fullWidth }) => $fullWidth && css`width: 100%;`}
    ${flatModeOverride}

    @media (max-width: 600px) {
        ${({ $size, $variant }) => getMobileSizeStyles($size, $variant)}
        ${({ $mobileFullWidth }) => $mobileFullWidth && css`
            width: 100%;
            text-align: center;
        `}
    }
`;

function Button({
    children,
    variant = 'primary',
    size = 'md',
    fullWidth = false,
    mobileFullWidth = false,
    loading = false,
    copied = false,
    disabled = false,
    minWidth,
    to,
    href,
    onClick,
    type = 'button',
    ...props
}) {
    const content = (
        <>
            {loading && <Spinner />}
            {children}
        </>
    );

    if (to) {
        return (
            <StyledLink
                to={to}
                $variant={variant}
                $size={size}
                $fullWidth={fullWidth}
                $mobileFullWidth={mobileFullWidth}
                $minWidth={minWidth}
                {...props}
            >
                {content}
            </StyledLink>
        );
    }

    if (href) {
        return (
            <StyledAnchor
                href={href}
                $variant={variant}
                $size={size}
                $fullWidth={fullWidth}
                $mobileFullWidth={mobileFullWidth}
                $minWidth={minWidth}
                target="_blank"
                rel="noopener noreferrer"
                {...props}
            >
                {content}
            </StyledAnchor>
        );
    }

    return (
        <StyledButton
            type={type}
            onClick={onClick}
            disabled={disabled || loading}
            $variant={variant}
            $size={size}
            $fullWidth={fullWidth}
            $mobileFullWidth={mobileFullWidth}
            $minWidth={minWidth}
            $copied={copied}
            {...props}
        >
            {content}
        </StyledButton>
    );
}

export default Button;
