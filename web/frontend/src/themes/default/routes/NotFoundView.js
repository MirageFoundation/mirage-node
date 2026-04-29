import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { HiOutlineMagnifyingGlass } from "react-icons/hi2";
import Button from "../components/Button.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { useNotFound } from "../../../logic/useNotFound";

/**
 * NotFoundView — `default` Plan 06 sub-plan 07.
 *
 * Rules (`docs/guides/web-theme-default/RULES.md`):
 *  - R1 centered panel sits on `theme.colors.bg` — no full-column fill.
 *  - R2 every color routed through a token; no raw shadows.
 *  - R3 no dividers — 404 is a single centered block.
 *  - R4 data parity with `themes/bluemoon/routes/NotFoundView.js` (code,
 *    title, path, back/home actions). Visual tone follows mobile app's
 *    empty-state pattern (icon circle + title + subtle message + CTA).
 *  - R7 big "404" is the hero 2rem/700 (hero surface exception); title
 *    1.1rem/700 page heading; message 0.75rem/500 subtle; path 0.62rem/500
 *    monospace subtle.
 */

const NotFoundWrap = styled.div`
    width: 100%;
    max-width: 820px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] & {
            width: 80%;
            max-width: none;
        }
    }
`;

const CenterBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 3rem 1.5rem;
    text-align: center;

    @media (max-width: 600px) {
        padding: 2rem 1rem;
    }
`;

const IconCircle = styled.div`
    width: 64px;
    height: 64px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};

    svg {
        width: 28px;
        height: 28px;
    }
`;

const Code = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1;
    margin-top: 0.35rem;
`;

const Title = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const Message = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.5;
    max-width: 24rem;
`;

const PathPill = styled.div`
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    padding: 0.3rem 0.55rem;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    word-break: break-all;
    overflow-wrap: anywhere;
    line-height: 1.35;
`;

const Actions = styled.div`
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-top: 0.35rem;
`;

function NotFoundView({ state }) {
    const { navigate, path } = useNotFound({ state });

    return (
        <ContentGrid>
            <Helmet>
                <title>404 — Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <TabbedContainer>
                        <ContainerBody $fullWidth>
                            <NotFoundWrap>
                                <CenterBlock>
                                    <IconCircle aria-hidden="true">
                                        <HiOutlineMagnifyingGlass />
                                    </IconCircle>
                                    <Code>404</Code>
                                    <Title>Page not found</Title>
                                    <Message>
                                        We couldn't find the page you were looking for. It may have been moved, deleted, or never existed.
                                    </Message>
                                    {path && <PathPill>{path}</PathPill>}
                                    <Actions>
                                        <Button
                                            size="sm"
                                            variant="subtle"
                                            onClick={() => navigate(-1)}
                                        >
                                            Go back
                                        </Button>
                                        <Button size="sm" variant="primary" to="/home">
                                            Go home
                                        </Button>
                                    </Actions>
                                </CenterBlock>
                            </NotFoundWrap>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

export default NotFoundView;
