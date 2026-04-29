import React, { useEffect } from "react";
import styled, { css } from "styled-components";

const Shell = styled.section`
    width: 100%;
    min-height: calc(100vh - 3.5rem);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 2.25rem 1rem 2rem;
    box-sizing: border-box;

    /* On desktop the Shell sits inside ModernPostFeed which is
       left-aligned within DefaultShell's Main column. Main itself is
       offset right by the sidebar + divider when the sidebar is
       visible, and even when the sidebar is hidden the Layout grid
       keeps a 17px divider track on the left. Centering inside any
       of those parents lands the Card off-axis from the topbar's
       viewport-centered search input.

       No DefaultShell ancestor (ShellRoot, Layout, Main, ContentGrid,
       ModernPostFeed) is positioned, so an absolutely positioned
       element here resolves its containing block to the initial
       containing block (the viewport for sizing purposes). That lets
       us anchor left: 0 + width: 100vw to the viewport edges
       directly, regardless of how deeply the Shell is nested or how
       its parents are offset. The Card then centers within that
       viewport-spanning Shell, landing on the same axis as the
       topbar's centered search input — at every screen size and
       whether the sidebar is shown or hidden.

       Mobile / tablet (≤ 1000px) keeps the simple in-flow centering
       since Main already spans the full viewport there. */
    @media (min-width: 1001px) {
        position: absolute;
        top: calc(2.5rem + 1px);
        left: 0;
        width: 100vw;
        max-width: 100vw;
        /* See LoggedOutPromptCard for the full rationale: a viewport-
           spanning absolute Shell would block clicks against the
           sidebar / page chrome, so disable pointer events on the
           Shell and re-enable them on the Card. */
        pointer-events: none;
    }
`;

const Card = styled.div`
    width: 100%;
    max-width: ${({ $wide }) => ($wide ? "44rem" : "24rem")};
    background: ${({ theme }) => theme.colors.bg};
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    /* Re-enable interaction inside the absolute, pointer-events: none
       Shell. Clicks outside the card pass through to the sidebar. */
    pointer-events: auto;

    /* TopBar.BarInner is a flex row: BrandLink ("MIRAGE", ~190px) +
       LeftSpacer (flex 1) + SearchWrapper + RightSpacer (flex 1) +
       right controls. With brand B on the left and right controls R
       on the right, the search input's center sits at (B - R)/2 px
       right of BarInner's center. For logged-out viewers R is just
       the Sign-in pill + GuestMenu (~120px), so the search center is
       roughly (190 - 120)/2 = 35px right of viewport center.

       In a justify-content: center flex row, a margin counts toward
       the centering box: an item with margin-left: m has its visual
       center shifted right by m/2. So margin-left: 70px lines this
       Card up directly under the search input. */
    @media (min-width: 1001px) {
        margin-left: 70px;
    }
`;

const Header = styled.header`
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 0.55rem;
`;

const HeadingGroup = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    align-items: center;
`;

export const AuthTitle = styled.h1`
    margin: 0;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    line-height: 1.25;
    letter-spacing: -0.01em;
    font-weight: 700;
`;

export const AuthDescription = styled.p`
    margin: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.72rem;
    line-height: 1.5;
    max-width: 100%;
    text-wrap: pretty;
`;

export const AuthBody = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
`;

export const AuthStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
`;

export const AuthPanel = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
`;

export const AuthSubtlePanel = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.65rem 0.75rem;
    border-radius: 0.65rem;
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
`;

export const AuthFieldRow = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
`;

export const AuthLabelRow = styled.div`
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
`;

export const AuthLabel = styled.label`
    display: block;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    font-weight: 600;
`;

export const AuthLabelHint = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
`;

const fieldStyles = css`
    width: 100%;
    box-sizing: border-box;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0.55rem;
    background: ${({ theme }) => theme.colors.bg};
    color: ${({ theme }) => theme.colors.text};
    padding: 0.55rem 0.7rem;
    font: inherit;
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.4;
    transition: border-color 0.15s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }

    &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
`;

export const AuthInput = styled.input`
    ${fieldStyles}
`;

export const AuthTextArea = styled.textarea`
    ${fieldStyles}
    min-height: 5.25rem;
    resize: vertical;
    font-size: 0.75rem;
    letter-spacing: 0.01em;
    line-height: 1.55;
`;

export const AuthHelperText = styled.p`
    margin: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1.45;
`;

export const AuthErrorMessage = styled.div`
    border-radius: 0.55rem;
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder || theme.colors.border};
    background: ${({ theme }) => theme.colors.buttonDangerBg || theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    padding: 0.55rem 0.7rem;
    font-size: 0.7rem;
    line-height: 1.4;
`;

export const AuthButtonRow = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    margin-top: 0.15rem;

    > * {
        width: 100%;
    }
`;

export const AuthFooter = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.72rem;
    line-height: 1.4;
    padding-top: 0.15rem;
`;

export const AuthLink = styled.a`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-weight: 600;

    &:hover {
        text-decoration: underline;
    }
`;

export const AuthTextButton = styled.button`
    align-self: center;
    padding: 0.2rem 0.4rem;
    border: none;
    background: none;
    color: ${({ theme }) => theme.colors.link};
    font: inherit;
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;

    &:hover {
        text-decoration: underline;
    }
`;

// Backwards-compatible aliases for existing consumers.
export const AuthLinkRow = AuthFooter;
export const AuthInlineBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.12rem 0.45rem;
    border-radius: 999px;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 600;
`;
export const AuthStepPill = AuthLabelHint;

function AuthPageShell({
    children,
    title,
    description,
    footer,
    wide = false,
}) {
    useEffect(() => {
        document.documentElement.classList.add('auth-page');
        return () => document.documentElement.classList.remove('auth-page');
    }, []);

    return (
        <Shell>
            <Card $wide={wide}>
                <Header>
                    {(title || description) ? (
                        <HeadingGroup>
                            {title ? <AuthTitle>{title}</AuthTitle> : null}
                            {description ? <AuthDescription>{description}</AuthDescription> : null}
                        </HeadingGroup>
                    ) : null}
                </Header>

                <AuthBody>
                    {children}
                </AuthBody>

                {footer ? <AuthFooter>{footer}</AuthFooter> : null}
            </Card>
        </Shell>
    );
}

export default AuthPageShell;
