import React from "react";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FAQ_MARKDOWN from "../../../content/faqMarkdown";

const FAQWrap = styled.div`
    width: 100%;
    max-width: 860px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }
`;

const FAQShellBody = styled(ContainerBody)`
    padding: 0.35rem 0 1rem;
    border: none;
    border-radius: 0;
`;

const HeaderRow = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding: 0.5rem 1rem 0.85rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};

    @media (max-width: 600px) {
        padding: 0.5rem 0 0.85rem;
    }
`;

const HeaderTitle = styled.h1`
    margin: 0;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    line-height: 1.25;
    letter-spacing: -0.01em;
`;

const HeaderDescription = styled.p`
    margin: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.5;
    max-width: 42rem;
`;

const SearchWrap = styled.label`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    max-width: 36rem;
`;

const SearchLabel = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
`;

const SearchInput = styled.input`
    width: 100%;
    box-sizing: border-box;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    font: inherit;
    font-size: 0.78rem;
    line-height: 1.2;
    padding: 0.65rem 0.9rem;
    outline: none;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:focus {
        border-color: ${({ theme }) => theme.colors.link};
        box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.focusBlue};
    }
`;

const SearchHint = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.68rem;
    line-height: 1.35;
`;

const FAQContent = styled.article`
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
    padding: 0.95rem 1rem 0;

    @media (max-width: 600px) {
        padding: 0.95rem 0 0;
    }
`;

const SectionBlock = styled.section`
    scroll-margin-top: 4rem;
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding-bottom: 0.45rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const SectionTitle = styled.h2`
    margin: 0;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.98rem;
    font-weight: 750;
    line-height: 1.25;
`;

const SectionCount = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.64rem;
    font-weight: 600;
    white-space: nowrap;
`;

const QuestionList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding-top: 0.65rem;
`;

const QuestionCard = styled.details`
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    background: ${({ theme }) => theme.colors.panel};
    scroll-margin-top: 4.5rem;
    overflow: hidden;

    &[open] {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
`;

const QuestionSummary = styled.summary`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.72rem 0.85rem;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1.35;
    list-style: none;

    &::-webkit-details-marker {
        display: none;
    }

    &::after {
        content: "+";
        flex: 0 0 auto;
        color: ${({ theme }) => theme.colors.subtleText};
        font-size: 1rem;
        font-weight: 600;
        line-height: 1;
    }

    ${QuestionCard}[open] & {
        border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    }

    ${QuestionCard}[open] &::after {
        content: "-";
    }

    &:hover,
    &:focus-visible {
        color: ${({ theme }) => theme.colors.link};
        outline: none;
    }
`;

const SummaryText = styled.span`
    flex: 1 1 auto;
    min-width: 0;
`;

const CopyLink = styled.a`
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 3.4rem;
    height: 1.35rem;
    padding: 0 0.45rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 999px;
    color: ${({ theme }) => theme.colors.subtleText};
    background: ${({ theme }) => theme.colors.panelAlt};
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    text-decoration: none;
    opacity: 0.75;

    &:hover,
    &:focus-visible {
        color: ${({ theme }) => theme.colors.link};
        border-color: ${({ theme }) => theme.colors.borderStrong};
        text-decoration: none;
        opacity: 1;
    }
`;

const AnswerBody = styled.div`
    padding: 0.75rem 0.85rem 0.85rem;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.76rem;
    font-weight: 500;
    line-height: 1.65;

    & p {
        margin: 0 0 0.75rem;
    }

    & p:last-child,
    & ul:last-child,
    & ol:last-child,
    & blockquote:last-child {
        margin-bottom: 0;
    }

    & ul,
    & ol {
        margin: 0.25rem 0 0.85rem 1.2rem;
        padding-left: 1.2rem;
    }

    & li {
        margin-bottom: 0.3rem;
    }

    & a {
        color: ${({ theme }) => theme.colors.link};
        text-decoration: none;
        overflow-wrap: anywhere;
    }

    & a:hover,
    & a:focus-visible {
        color: ${({ theme }) => theme.colors.linkHover};
        text-decoration: underline;
    }

    & code {
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: 0.72rem;
        background: ${({ theme }) => theme.colors.surface2};
        border: 1px solid ${({ theme }) => theme.colors.border};
        border-radius: 4px;
        padding: 0.05rem 0.25rem;
    }

    & pre {
        overflow-x: auto;
        background: ${({ theme }) => theme.colors.surface2};
        border: 1px solid ${({ theme }) => theme.colors.border};
        border-radius: 8px;
        padding: 0.75rem;
    }

    & pre code {
        border: none;
        background: transparent;
        padding: 0;
    }

    & blockquote {
        margin: 0.5rem 0 0.85rem;
        padding-left: 0.8rem;
        border-left: 3px solid ${({ theme }) => theme.colors.border};
        color: ${({ theme }) => theme.colors.text};
    }
`;

const EmptyState = styled.div`
    padding: 1rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    background: ${({ theme }) => theme.colors.panel};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.76rem;
    font-weight: 600;
    line-height: 1.5;
`;

function cleanHeading(raw) {
    return String(raw || '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/[`*_]/g, '')
        .trim();
}

function slugify(raw) {
    return cleanHeading(raw)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

function uniqueId(text, seen) {
    const base = slugify(text);
    if (!base) throw new Error('FAQ heading produced an empty id.');
    const count = seen.get(base) || 0;
    seen.set(base, count + 1);
    return count === 0 ? base : `${base}-${count + 1}`;
}

function markdownFromLines(lines) {
    let start = 0;
    let end = lines.length;
    while (start < end && lines[start].trim() === '') start += 1;
    while (end > start && lines[end - 1].trim() === '') end -= 1;
    return lines.slice(start, end).join('\n');
}

function parseFAQ(markdown) {
    const lines = String(markdown || '').split(/\r?\n/);
    const seen = new Map();
    const sections = [];
    let title = '';
    let currentSection = null;
    let currentQuestion = null;

    lines.forEach(line => {
        const h1 = /^#\s+(.+?)\s*$/.exec(line);
        if (h1) {
            title = cleanHeading(h1[1]);
            return;
        }

        const h2 = /^##\s+(.+?)\s*$/.exec(line);
        if (h2) {
            const text = cleanHeading(h2[1]);
            currentSection = {
                title: text,
                id: uniqueId(text, seen),
                questions: [],
            };
            sections.push(currentSection);
            currentQuestion = null;
            return;
        }

        const h3 = /^###\s+(.+?)\s*$/.exec(line);
        if (h3) {
            if (!currentSection) {
                throw new Error('FAQ question appeared before a section.');
            }
            const text = cleanHeading(h3[1]);
            currentQuestion = {
                title: text,
                id: uniqueId(text, seen),
                bodyLines: [],
            };
            currentSection.questions.push(currentQuestion);
            return;
        }

        if (currentQuestion) {
            currentQuestion.bodyLines.push(line);
        }
    });

    const parsedSections = sections.map(section => ({
        ...section,
        questions: section.questions.map(question => ({
            title: question.title,
            id: question.id,
            markdown: markdownFromLines(question.bodyLines),
        })),
    }));

    const questionCount = parsedSections.reduce((total, section) => total + section.questions.length, 0);
    if (!title || parsedSections.length === 0 || questionCount === 0) {
        throw new Error('FAQ markdown must contain a title, sections, and questions.');
    }

    return { title, sections: parsedSections, questionCount };
}

function normalizeSearch(value) {
    return String(value || '').trim().toLowerCase();
}

function readHashId() {
    if (typeof window === 'undefined') return '';
    const raw = (window.location.hash || '').replace(/^#/, '');
    try {
        return decodeURIComponent(raw);
    } catch (_) {
        return raw;
    }
}

function filterFAQ(faq, query) {
    const needle = normalizeSearch(query);
    if (!needle) return faq.sections;

    return faq.sections
        .map(section => {
            const sectionMatches = section.title.toLowerCase().includes(needle);
            const questions = section.questions.filter(question => {
                const haystack = `${section.title}\n${question.title}\n${question.markdown}`.toLowerCase();
                return sectionMatches || haystack.includes(needle);
            });
            return { ...section, questions };
        })
        .filter(section => section.questions.length > 0);
}

function MarkdownLink({ href, children }) {
    const external = /^https?:\/\//i.test(String(href || ''));
    return (
        <a
            href={href}
            target={external ? '_blank' : undefined}
            rel={external ? 'noopener noreferrer' : undefined}
        >
            {children}
        </a>
    );
}

function AnswerMarkdown({ children }) {
    return (
        <AnswerBody>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                    a: ({ href, children: linkChildren }) => (
                        <MarkdownLink href={href}>{linkChildren}</MarkdownLink>
                    ),
                }}
            >
                {children}
            </ReactMarkdown>
        </AnswerBody>
    );
}

export default function FAQView() {
    const faq = React.useMemo(() => parseFAQ(FAQ_MARKDOWN), []);
    const [query, setQuery] = React.useState('');
    const [activeId, setActiveId] = React.useState(readHashId);
    const [copiedId, setCopiedId] = React.useState('');
    const copyTimer = React.useRef(0);
    const visibleSections = React.useMemo(() => filterFAQ(faq, query), [faq, query]);
    const hasQuery = normalizeSearch(query).length > 0;
    const visibleQuestionCount = visibleSections.reduce((total, section) => total + section.questions.length, 0);

    // Deep-linking: open and scroll to the targeted entry once it has rendered.
    const scrollToId = React.useCallback((id) => {
        if (!id || typeof window === 'undefined') return;
        window.setTimeout(() => {
            const el = document.getElementById(id);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 60);
    }, []);

    React.useEffect(() => {
        const id = readHashId();
        if (id) scrollToId(id);
    }, [scrollToId]);

    React.useEffect(() => {
        const onHash = () => {
            const id = readHashId();
            setActiveId(id);
            if (id) scrollToId(id);
        };
        window.addEventListener('hashchange', onHash);
        return () => window.removeEventListener('hashchange', onHash);
    }, [scrollToId]);

    React.useEffect(() => () => window.clearTimeout(copyTimer.current), []);

    const copyQuestionLink = React.useCallback((event, id) => {
        event.preventDefault();
        event.stopPropagation();
        const { origin, pathname, search } = window.location;
        const url = `${origin}${pathname}${search}#${id}`;
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(url);
            }
        } catch (_) { /* clipboard unavailable */ }
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, '', `${pathname}${search}#${id}`);
        }
        setActiveId(id);
        setCopiedId(id);
        window.clearTimeout(copyTimer.current);
        copyTimer.current = window.setTimeout(() => setCopiedId(''), 1500);
    }, []);

    return (
        <ContentGrid>
            <Helmet>
                <title>FAQ | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <FAQShellBody>
                                <FAQWrap>
                                    <HeaderRow>
                                        <HeaderTitle>Frequently Asked Questions</HeaderTitle>
                                        <HeaderDescription>
                                            Straight answers about Mirage, moderation, safety, nodes, tokens, and how the network works.
                                        </HeaderDescription>
                                        <SearchWrap>
                                            <SearchLabel>Search FAQ</SearchLabel>
                                            <SearchInput
                                                type="search"
                                                value={query}
                                                onChange={event => setQuery(event.target.value)}
                                                placeholder="Try subscriptions, nodes, privacy..."
                                            />
                                            <SearchHint>
                                                {hasQuery
                                                    ? `${visibleQuestionCount} matching question${visibleQuestionCount === 1 ? '' : 's'}`
                                                    : `${faq.questionCount} questions across ${faq.sections.length} sections`}
                                            </SearchHint>
                                        </SearchWrap>
                                    </HeaderRow>
                                    <FAQContent>
                                        {visibleSections.length === 0 ? (
                                            <EmptyState>No FAQ entries match that search.</EmptyState>
                                        ) : visibleSections.map((section, sectionIndex) => (
                                            <SectionBlock key={section.id} id={section.id}>
                                                <SectionHeader>
                                                    <SectionTitle>{section.title}</SectionTitle>
                                                    <SectionCount>
                                                        {section.questions.length} question{section.questions.length === 1 ? '' : 's'}
                                                    </SectionCount>
                                                </SectionHeader>
                                                <QuestionList>
                                                    {section.questions.map((question, questionIndex) => (
                                                        <QuestionCard
                                                            key={question.id}
                                                            id={question.id}
                                                            open={hasQuery || question.id === activeId || (sectionIndex === 0 && questionIndex === 0)}
                                                        >
                                                            <QuestionSummary>
                                                                <SummaryText>{question.title}</SummaryText>
                                                                <CopyLink
                                                                    href={`#${question.id}`}
                                                                    onClick={event => copyQuestionLink(event, question.id)}
                                                                    title="Copy link to this question"
                                                                    aria-label="Copy link to this question"
                                                                >
                                                                    {copiedId === question.id ? 'Copied' : 'Link'}
                                                                </CopyLink>
                                                            </QuestionSummary>
                                                            <AnswerMarkdown>{question.markdown}</AnswerMarkdown>
                                                        </QuestionCard>
                                                    ))}
                                                </QuestionList>
                                            </SectionBlock>
                                        ))}
                                    </FAQContent>
                                </FAQWrap>
                            </FAQShellBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>
    );
}
