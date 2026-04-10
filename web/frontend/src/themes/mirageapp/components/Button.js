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
    transition: all 0.15s ease;
    white-space: nowrap;
    border: none;
    font-family: inherit;
    
    &:focus {
        outline: none;
    }
    
    &:focus-visible {
        outline: 2px solid #667eea;
        outline-offset: 2px;
        box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.25);
    }
    
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
        transform: none !important;
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
        border-radius: 6px;
            `;
        case 'lg':
            return css`
        padding: 0.6rem 1.5rem;
        font-size: 0.95rem;
        border-radius: 10px;
            `;
        case 'pill':
            return css`
        padding: 0.55rem 0.85rem;
        font-size: 0.85rem;
        border-radius: 18px;
            `;
        case 'md':
        default:
            return css`
                padding: 0.5rem 1rem;
                font-size: 0.85rem;
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
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
        
        &:hover:not(:disabled) {
                    background: ${theme.colors.accent};
            box-shadow: 0 8px 22px rgba(0, 0, 0, 0.16);
        }
            `;
        case 'danger':
            return css`
                background: ${({ theme }) => theme.colors.buttonDangerBg};
        color: #dc2626;
                border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
        
        &:hover:not(:disabled) {
                    background: ${({ theme }) => theme.colors.buttonDangerHoverBg};
        }
            `;
        case 'success':
            return css`
                background: ${({ theme }) => theme.colors.buttonSuccessBg};
        color: #22c55e;
                border: 1px solid ${({ theme }) => theme.colors.buttonSuccessBorder};
        
        &:hover:not(:disabled) {
                    background: ${({ theme }) => theme.colors.buttonSuccessHoverBg};
        }
            `;
        case 'warning':
            return css`
        background: #f59e0b;
        color: #000;
        border: none;
        
        &:hover:not(:disabled) {
            background: #d97706;
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
                    border-color: ${theme.colors.text};
                    transform: translateY(-1px);
                }
                
                &:active:not(:disabled) {
                    transform: translateY(0);
        }
            `;
        case 'subtle':
            return css`
                background: rgba(102, 126, 234, 0.15);
                color: ${theme.colors.text};
                border: 1px solid rgba(102, 126, 234, 0.3);
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
                
                &:hover:not(:disabled) {
                    background: rgba(102, 126, 234, 0.25);
                    border-color: rgba(102, 126, 234, 0.5);
                    box-shadow: 0 6px 16px rgba(102, 126, 234, 0.25);
                    transform: translateY(-1px);
                }
                
                &:active:not(:disabled) {
                    transform: translateY(0);
                }
            `;
        case 'link':
            return css`
        background: transparent;
                color: ${theme.colors.link};
        border: none;
        padding: 0;
        box-shadow: none;
        
        &:hover:not(:disabled) {
            text-decoration: underline;
        }
            `;
        case 'primaryDanger':
            return css`
                background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
                color: #FFFFFF;
                border: 1px solid transparent;
                box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3);
                
                &:hover:not(:disabled) {
                    box-shadow: 0 6px 16px rgba(220, 38, 38, 0.45);
                    transform: translateY(-1px);
                }
                
                &:active:not(:disabled) {
                    transform: translateY(0);
                }
            `;
        case 'primary':
        default:
            return css`
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #FFFFFF;
                border: 1px solid transparent;
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
                
                &:hover:not(:disabled) {
                    box-shadow: 0 6px 16px rgba(102, 126, 234, 0.45);
                    transform: translateY(-1px);
                }
                
                &:active:not(:disabled) {
                    transform: translateY(0);
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
        border-radius: 6px;
            `;
        case 'lg':
            return css`
        padding: 0.5rem 1.2rem;
        font-size: 0.9rem;
        border-radius: 10px;
            `;
        case 'pill':
            return css`
        padding: 0.45rem 0.75rem;
        font-size: 0.8rem;
        border-radius: 16px;
            `;
        case 'md':
        default:
            return css`
                padding: 0.4rem 0.85rem;
                font-size: 0.8rem;
                border-radius: 8px;
            `;
    }
};

const StyledButton = styled.button`
    ${baseStyles}
    ${({ $size }) => getSizeStyles($size)}
    ${({ $variant, theme }) => getVariantStyles($variant, theme)}
    ${({ $fullWidth }) => $fullWidth && css`width: 100%;`}
    ${({ $copied }) => $copied && css`
        background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
        color: #FFFFFF !important;
    `}
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
