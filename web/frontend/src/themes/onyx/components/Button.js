import React from 'react';
import styled, { css, keyframes } from 'styled-components';
import { Link } from 'react-router-dom';

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

const baseStyles = css`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    white-space: nowrap;
    border: none;
    font-family: inherit;
    
    &:focus {
        outline: none;
    }
    
    &:focus-visible {
        outline: 1px solid ${({ theme }) => theme.colors.focusBorder};
        outline-offset: 2px;
    }
    
    &:disabled {
        opacity: 0.5;
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
                padding: 0.25rem 0.5rem;
                font-size: 0.65rem;
                border-radius: 4px;
            `;
        case 'sm':
            return css`
                padding: 0.4rem 0.75rem;
                font-size: 0.75rem;
                border-radius: 4px;
            `;
        case 'lg':
            return css`
                padding: 0.6rem 1.5rem;
                font-size: 0.95rem;
                border-radius: 6px;
            `;
        case 'pill':
            return css`
                padding: 0.55rem 0.85rem;
                font-size: 0.85rem;
                border-radius: 4px;
            `;
        case 'md':
        default:
            return css`
                padding: 0.5rem 1rem;
                font-size: 0.85rem;
                border-radius: 4px;
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
                }
            `;
        case 'danger':
            return css`
                background: ${theme.colors.dangerBg};
                color: ${theme.colors.danger};
                border: 1px solid ${theme.colors.dangerBorder};
                
                &:hover:not(:disabled) {
                    background: ${theme.colors.danger};
                    color: ${theme.colors.bg};
                }
            `;
        case 'success':
            return css`
                background: ${theme.colors.successBg};
                color: ${theme.colors.success};
                border: 1px solid ${theme.colors.successBorder};
                
                &:hover:not(:disabled) {
                    background: ${theme.colors.success};
                    color: ${theme.colors.bg};
                }
            `;
        case 'warning':
            return css`
                background: ${theme.colors.warningBg};
                color: ${theme.colors.warning};
                border: 1px solid ${theme.colors.warningBorder};
                
                &:hover:not(:disabled) {
                    background: ${theme.colors.warning};
                    color: ${theme.colors.bg};
                }
            `;
        case 'ghost':
            return css`
                background: transparent;
                color: ${theme.colors.subtleText};
                border: 1px solid ${theme.colors.border};
                
                &:hover:not(:disabled) {
                    background: ${theme.colors.panelAlt};
                    color: ${theme.colors.text};
                }
            `;
        case 'subtle':
            return css`
                background: ${theme.colors.panelAlt};
                color: ${theme.colors.text};
                border: 1px solid ${theme.colors.border};
                
                &:hover:not(:disabled) {
                    background: ${theme.colors.accent};
                    border-color: ${theme.colors.borderStrong};
                }
            `;
        case 'link':
            return css`
                background: transparent;
                color: ${theme.colors.link};
                border: none;
                padding: 0;
                
                &:hover:not(:disabled) {
                    text-decoration: underline;
                }
            `;
        case 'primaryDanger':
            return css`
                background: ${theme.colors.danger};
                color: ${theme.colors.bg};
                border: 1px solid ${theme.colors.danger};
                
                &:hover:not(:disabled) {
                    opacity: 0.85;
                }
            `;
        case 'primary':
        default:
            return css`
                background: ${theme.colors.panelAlt};
                color: ${theme.colors.text};
                border: 1px solid ${theme.colors.border};
                
                &:hover:not(:disabled) {
                    background: ${theme.colors.accent};
                    border-color: ${theme.colors.borderStrong};
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
                padding: 0.2rem 0.45rem;
                font-size: 0.6rem;
                border-radius: 4px;
            `;
        case 'sm':
            return css`
                padding: 0.35rem 0.6rem;
                font-size: 0.7rem;
                border-radius: 4px;
            `;
        case 'lg':
            return css`
                padding: 0.5rem 1.2rem;
                font-size: 0.9rem;
                border-radius: 6px;
            `;
        case 'pill':
            return css`
                padding: 0.45rem 0.75rem;
                font-size: 0.8rem;
                border-radius: 4px;
            `;
        case 'md':
        default:
            return css`
                padding: 0.4rem 0.85rem;
                font-size: 0.8rem;
                border-radius: 4px;
            `;
    }
};

const StyledButton = styled.button`
    ${baseStyles}
    ${({ $size }) => getSizeStyles($size)}
    ${({ $variant, theme }) => getVariantStyles($variant, theme)}
    ${({ $fullWidth }) => $fullWidth && css`width: 100%;`}
    ${({ $copied, theme }) => $copied && css`
        background: ${theme.colors.success} !important;
        color: ${theme.colors.bg} !important;
        border-color: ${theme.colors.success} !important;
    `}
    
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
