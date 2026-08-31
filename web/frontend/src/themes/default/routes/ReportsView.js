import { Helmet } from "react-helmet-async";
import { Link, Navigate } from "react-router-dom";
import styled from "styled-components";
import {
    HiExclamationTriangle,
    HiFlag,
    HiLockClosed,
    HiTrash,
    HiCheck,
} from "react-icons/hi2";
import Button from "../components/Button.js";
import { ListRowSkeletonList, PageHeaderSkeleton } from "../components/Skeleton.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import { useReports } from "../../../logic/useReports";

/**
 * ReportsView — `default` Plan 06 sub-plan 03.
 *
 * Moderator-only list of active reports. Rules applied:
 *  - R1 rows sit on `theme.colors.bg`.
 *  - R2 all colors routed through tokens (voteUpBg / voteDownBg / neutral chips).
 *  - R3 rows divided by `1px solid theme.colors.border`.
 *  - R4 data parity with `themes/bluemoon/routes/ReportsView.js`.
 *  - R7 row title 0.78rem/600, meta 0.62rem/500 subtleText.
 *
 * Shell structure mirrors `InboxView` / `FollowsView` / `BlocksView` /
 * `AgentsView`: `FeedRailRow` + `FeedCol` so the page keeps the standard
 * responsive width bumps every other list route in the theme uses.
 */

const ReportsWrap = styled.div`
    width: 100%;
    max-width: 820px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1500px) {
        max-width: 960px;
    }

    @media (min-width: 1900px) {
        max-width: 1200px;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.5rem;
    padding: 0.25rem 1rem 0.5rem;

    @media (max-width: 600px) {
        padding: 0.25rem 0 0.5rem;
    }
`;

const HeaderTitle = styled.div`
    display: flex;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const HeaderCount = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
`;

const List = styled.div`
    display: flex;
    flex-direction: column;
`;

const ReportRow = styled.article`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    padding: 0.65rem 1rem 0.75rem;
    background: transparent;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};

    @media (max-width: 600px) {
        padding: 0.55rem 0 0.7rem;
    }
`;

const TopRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
`;

const ReporterLabel = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
`;

const ReporterName = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.25;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const TopSpacer = styled.span`
    flex: 1;
    min-width: 0.5rem;
`;

/**
 * Status chip. Per sub-plan 06.3 uses:
 *  - `voteUpBg` for success states
 *  - `voteDownBg` for danger/flagged states
 *  - neutral tile for idle/pending
 * Active listed reports are always "Pending" until acted on (neutral tile).
 */
const StatusChip = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    white-space: nowrap;

    ${({ $tone, theme }) => {
        if ($tone === 'danger') {
            return `
                background: ${theme.colors.voteDownBg};
                color: ${theme.colors.voteDown};
            `;
        }
        if ($tone === 'success') {
            return `
                background: ${theme.colors.voteUpBg};
                color: ${theme.colors.voteUp};
            `;
        }
        return `
            background: ${theme.colors.surface2};
            color: ${theme.colors.subtleText};
        `;
    }}
`;

const TimeText = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    white-space: nowrap;
`;

const MetaGrid = styled.div`
    display: grid;
    grid-template-columns: 5rem 1fr;
    gap: 0.15rem 0.55rem;
    align-items: baseline;

    @media (max-width: 600px) {
        grid-template-columns: 4.25rem 1fr;
    }
`;

const MetaLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.02em;
`;

const MetaValue = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.35;
    min-width: 0;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

const StyledLink = styled(Link)`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-weight: 500;
    word-break: break-all;
    overflow-wrap: anywhere;

    &:hover {
        color: ${({ theme }) => theme.colors.linkHover};
        text-decoration: underline;
    }
`;

const UserText = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.68rem;
    word-break: break-all;
    overflow-wrap: anywhere;
`;

const QuoteBlock = styled.blockquote`
    margin: 0.15rem 0 0;
    padding: 0.35rem 0.55rem;
    background: ${({ theme }) => theme.colors.surface2};
    border-left: 2px solid ${({ theme }) => theme.colors.border};
    border-radius: 4px;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

const QuoteTitle = styled(QuoteBlock)`
    font-weight: 600;
`;

const Actions = styled.div`
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-top: 0.2rem;

    @media (max-width: 600px) {
        flex-direction: column;
        gap: 0.3rem;
    }
`;

/* ----- State blocks (mirror InboxView). ----- */

const StateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.6rem;
    padding: 2.5rem 1.25rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const StateIcon = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};

    svg {
        width: 22px;
        height: 22px;
        color: ${({ $tone, theme }) => ($tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText)};
    }
`;

const StateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: 700;
`;

const StateMessage = styled.div`
    font-size: 0.75rem;
    line-height: 1.5;
    max-width: 24rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const shortenReporter = addr => {
    if (!addr) return '';
    return `${addr.slice(0, 10)}…${addr.slice(-4)}`;
};

const fmtTime = ts => {
    try {
        return new Date((Number(ts) || 0) * 1000).toLocaleString();
    } catch (_) {
        return String(ts);
    }
};

const stripImages = content => {
    if (!content || typeof content !== 'string') return '';
    return content.replace(/!\[.*?\]\((.*?)\)/g, '$1');
};

export default function ReportsView({ state }) {
    const {
        reports,
        loading,
        error,
        userLevel,
        processing,
        processingAction,
        onDelete,
        onIgnore,
    } = useReports({ state });

    const viewerAddress = state && state.publicKey ? state.publicKey : '';

    const renderShell = (body, titleCount, loadingHeader = false) => (
        <ContentGrid>
            <Helmet>
                <title>Reports | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerBody $fullWidth>
                                <ReportsWrap>
                                    {loadingHeader ? (
                                        <PageHeaderSkeleton showSubtitle={false} titleWidth="30%" />
                                    ) : (
                                        <HeaderRow>
                                            <HeaderTitle>Reports</HeaderTitle>
                                            {typeof titleCount === 'number' && (
                                                <HeaderCount>({titleCount})</HeaderCount>
                                            )}
                                        </HeaderRow>
                                    )}
                                    {body}
                                </ReportsWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>
    );

    if (!viewerAddress) {
        return <Navigate to="/home" replace />;
    }

    if (userLevel < 100) {
        return renderShell(
            <StateBlock role="alert">
                <StateIcon $tone="danger">
                    <HiLockClosed />
                </StateIcon>
                <StateTitle>Forbidden</StateTitle>
                <StateMessage>
                    You don’t have permission to view moderator reports.
                </StateMessage>
            </StateBlock>
        );
    }

    if (loading) {
        return renderShell(
            <ListRowSkeletonList count={5} />,
            undefined,
            true
        );
    }

    if (error) {
        return renderShell(
            <StateBlock role="alert">
                <StateIcon $tone="danger">
                    <HiExclamationTriangle />
                </StateIcon>
                <StateTitle>Couldn’t load reports</StateTitle>
                <StateMessage>{error}</StateMessage>
            </StateBlock>
        );
    }

    if (reports.length === 0) {
        return renderShell(
            <StateBlock>
                <StateIcon>
                    <HiFlag />
                </StateIcon>
                <StateTitle>No active reports</StateTitle>
                <StateMessage>
                    When users report posts, they appear here for moderator review.
                </StateMessage>
            </StateBlock>,
            0
        );
    }

    return renderShell(
        <List>
            {reports.map(r => {
                const isProcessing = processing.has(r.id);
                // Which specific action is in flight for this row, so the
                // spinner only appears on the button that was clicked
                // instead of both. Falls back to `null` when idle.
                const activeAction = (processingAction && processingAction.get)
                    ? (processingAction.get(r.id) || null)
                    : null;
                const isDeleting = activeAction === 'delete';
                const isIgnoring = activeAction === 'ignore';
                const targetId = String(r.target || '');
                const reporterLabel = r.reporter_username || shortenReporter(r.reporter_owner);
                const ownerLabel = r.post_username || (r.post_owner ? shortenReporter(r.post_owner) : '');
                return (
                    <ReportRow key={r.id}>
                        <TopRow>
                            <ReporterLabel>Reporter</ReporterLabel>
                            <ReporterName title={r.reporter_owner}>{reporterLabel}</ReporterName>
                            <TopSpacer />
                            <StatusChip $tone={isProcessing ? 'danger' : 'neutral'}>
                                {isProcessing ? 'Processing' : 'Pending'}
                            </StatusChip>
                            <TimeText>{fmtTime(r.timestamp)}</TimeText>
                        </TopRow>

                        <MetaGrid>
                            <MetaLabel>Reason</MetaLabel>
                            <MetaValue>{r.reason}</MetaValue>

                            <MetaLabel>Target</MetaLabel>
                            <MetaValue>
                                <StyledLink to={`/p/${encodeURIComponent(targetId)}`}>
                                    {targetId}
                                </StyledLink>
                            </MetaValue>

                            {r.post_owner && (
                                <>
                                    <MetaLabel>Owner</MetaLabel>
                                    <MetaValue>
                                        <UserText title={r.post_owner}>{ownerLabel}</UserText>
                                    </MetaValue>
                                </>
                            )}
                        </MetaGrid>

                        {r.title && <QuoteTitle>{r.title}</QuoteTitle>}
                        {typeof r.content === 'string' && r.content.length > 0 && (
                            <QuoteBlock>{stripImages(r.content)}</QuoteBlock>
                        )}

                        <Actions>
                            <Button
                                variant="danger"
                                size="sm"
                                onClick={() => onDelete(r)}
                                disabled={isProcessing}
                                loading={isDeleting}
                                mobileFullWidth
                            >
                                {!isDeleting && <HiTrash aria-hidden="true" />}
                                Delete post
                            </Button>
                            <Button
                                variant="success"
                                size="sm"
                                onClick={() => onIgnore(r)}
                                disabled={isProcessing}
                                loading={isIgnoring}
                                mobileFullWidth
                            >
                                {!isIgnoring && <HiCheck aria-hidden="true" />}
                                Ignore report
                            </Button>
                        </Actions>
                    </ReportRow>
                );
            })}
        </List>,
        reports.length
    );
}
