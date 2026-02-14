import React, { useState } from "react";
import styled from "styled-components";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import InlineMedia from "./InlineMedia";

const Container = styled.div`
	/* Headers with underline */
	& h1, & h2, & h3, & h4, & h5, & h6 {
		margin: 1rem 0 0.5rem 0;
		font-weight: 700;
		text-decoration: underline;
	}
	& h1 { font-size: 1.25rem; }
	& h2 { font-size: 1.1rem; }
	& h3 { font-size: 1rem; }
	& h4, & h5, & h6 { font-size: 0.9rem; }
	& h1:first-child, & h2:first-child, & h3:first-child {
		margin-top: 0;
	}
	/* Restore sensible list indentation (global reset sets margins/padding to 0) */
	& ul,
	& ol {
		margin: 0.25rem 0 0.75rem 1.2rem;
		padding-left: 1.2rem;
	}
	/* Restore paragraph spacing so double-newlines create visible gaps */
	& p {
		margin-bottom: 0.75rem;
	}
	& p:last-child {
		margin-bottom: 0;
	}
	/* Make blockquotes visibly distinct (global reset zeroed margins) */
	& blockquote {
		margin: 0.5rem 0 0.75rem 0;
		padding-left: 0.75rem;
		border-left: 3px solid ${({ theme }) => theme?.colors?.border || '#444'};
		color: ${({ theme }) => theme?.colors?.text || '#CCCCCC'};
	}
	& blockquote > :last-child {
		margin-bottom: 0;
	}
	/* Horizontal rules need spacing to separate content */
	& hr {
		margin: 0.75rem 0;
		border: none;
		border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
	}
`;

const SpoilerSpan = styled.span`
	background-color: ${({ theme }) => theme?.colors?.text || '#ccc'};
	color: transparent;
	cursor: pointer;
	border-radius: 3px;
	padding: 0 0.2em;
	transition: background-color 0.3s ease, color 0.3s ease;
	user-select: none;

	&.revealed {
		background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2a2d31'};
		color: ${({ theme }) => theme?.colors?.text || '#ccc'};
		user-select: text;
	}
`;

const MentionLink = styled.a`
	color: ${({ theme }) => theme?.colors?.accent || '#667eea'};
	font-weight: 600;
	text-decoration: none;
	cursor: pointer;
	&:hover {
		text-decoration: underline;
	}
`;

function Spoiler({ children }) {
    const [revealed, setRevealed] = useState(false);
    return (
        <SpoilerSpan
            className={revealed ? 'revealed' : ''}
            onClick={() => setRevealed(r => !r)}
            title={revealed ? 'Click to hide' : 'Click to reveal spoiler'}
        >
            {children}
        </SpoilerSpan>
    );
}

/**
 * Remark plugin: converts ||spoiler text|| into inline spoiler nodes.
 * The node uses data.hName = 'spoiler-tag' so react-markdown maps it
 * through the components prop to our interactive <Spoiler> component.
 */
function remarkSpoiler() {
    return (tree) => {
        visit(tree, 'text', (node, index, parent) => {
            if (!node.value || typeof node.value !== 'string') return;
            if (!node.value.includes('||')) return;

            const regex = /\|\|(.+?)\|\|/g;
            const parts = [];
            let lastIndex = 0;
            let match;

            while ((match = regex.exec(node.value)) !== null) {
                if (match.index > lastIndex) {
                    parts.push({ type: 'text', value: node.value.slice(lastIndex, match.index) });
                }
                parts.push({
                    type: 'spoiler',
                    data: { hName: 'spoiler-tag' },
                    children: [{ type: 'text', value: match[1] }],
                });
                lastIndex = match.index + match[0].length;
            }

            if (lastIndex === 0) return; // no spoilers found

            if (lastIndex < node.value.length) {
                parts.push({ type: 'text', value: node.value.slice(lastIndex) });
            }

            if (parent && Array.isArray(parent.children)) {
                parent.children.splice(index, 1, ...parts);
                return index + parts.length;
            }
        });
    };
}

/**
 * Remark plugin: converts @username into clickable profile links.
 * The node uses data.hName = 'mention-tag' so react-markdown maps it
 * through the components prop to our styled <MentionLink> component.
 */
function remarkMentions() {
    return (tree) => {
        visit(tree, 'text', (node, index, parent) => {
            if (!node.value || typeof node.value !== 'string') return;
            if (!node.value.includes('@')) return;

            const regex = /(?<!\w)@([A-Za-z0-9-]+)/g;
            const parts = [];
            let lastIndex = 0;
            let match;

            while ((match = regex.exec(node.value)) !== null) {
                if (match.index > lastIndex) {
                    parts.push({ type: 'text', value: node.value.slice(lastIndex, match.index) });
                }
                parts.push({
                    type: 'mention',
                    data: {
                        hName: 'mention-tag',
                        hProperties: { username: match[1] },
                    },
                    children: [{ type: 'text', value: '@' + match[1] }],
                });
                lastIndex = match.index + match[0].length;
            }

            if (lastIndex === 0) return; // no mentions found

            if (lastIndex < node.value.length) {
                parts.push({ type: 'text', value: node.value.slice(lastIndex) });
            }

            if (parent && Array.isArray(parent.children)) {
                parent.children.splice(index, 1, ...parts);
                return index + parts.length;
            }
        });
    };
}

/**
 * AST transformation to treat soft line breaks (single newlines) as hard breaks.
 * This mimics GitHub-style line breaks where a single Enter creates a new line.
 * 
 * It visits all text nodes and replaces single newlines with a "break" node,
 * unless the newline is part of a paragraph break (double newline).
 */
function remarkSoftBreaks() {
    return (tree) => {
        visit(tree, 'text', (node, index, parent) => {
            if (!node.value || typeof node.value !== 'string') return;

            // Check if the text contains newlines
            if (!node.value.includes('\n')) return;

            // Split text by newlines to inspect them
            // We want to find single newlines that aren't part of a larger gap
            const parts = node.value.split(/(\n)/);
            const newChildren = [];

            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];

                if (part === '\n') {
                    // Look ahead/behind to see if this is a lonely newline
                    const prev = parts[i - 1];
                    const next = parts[i + 1];

                    // If surrounded by other newlines or empty strings (from split),
                    // it's likely a multi-newline gap -> preserve as text (paragraph break)
                    // Otherwise, it's a soft break -> convert to <br>
                    const isSoft =
                        (prev && prev !== '\n' && prev.trim() !== '') &&
                        (next && next !== '\n' && next.trim() !== '');

                    if (isSoft) {
                        newChildren.push({ type: 'break' });
                    } else {
                        // Keep as text newline (will become space or paragraph break)
                        // If we already have a text node at the end, append to it
                        const last = newChildren[newChildren.length - 1];
                        if (last && last.type === 'text') {
                            last.value += '\n';
                        } else {
                            newChildren.push({ type: 'text', value: '\n' });
                        }
                    }
                } else if (part) {
                    // Regular text content
                    const last = newChildren[newChildren.length - 1];
                    if (last && last.type === 'text') {
                        last.value += part;
                    } else {
                        newChildren.push({ type: 'text', value: part });
                    }
                }
            }

            // Replace the original text node with our new sequence of nodes
            if (parent && Array.isArray(parent.children)) {
                parent.children.splice(index, 1, ...newChildren);
                // Skip over the newly inserted nodes to avoid infinite recursion
                return index + newChildren.length;
            }
        });
    };
}

function normalizeEmptyLines(text) {
    if (!text || typeof text !== "string") return text || "";
    // Preserve intentional spacing: 3+ blank lines become 2 blank lines (extra paragraph break)
    // 2 blank lines stay as 1 blank line (normal paragraph break)
    return text
        .replace(/(\r?\n\s*){3,}/g, "\n\n&nbsp;\n\n")  // 3+ lines: add visible spacer
        .replace(/(\r?\n\s*){2}/g, "\n\n");            // 2 lines: normal paragraph
}

export default function MarkdownRenderer({ text }) {
    const normalized = normalizeEmptyLines(text || "");

    return (
        <Container>
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkSpoiler, remarkMentions, remarkSoftBreaks]}
                components={{
                    img: ({ src }) => <InlineMedia url={src} />,
                    a: ({ href, children }) => (
                        // eslint-disable-next-line jsx-a11y/anchor-has-content
                        <a href={href} target="_blank" rel="noopener noreferrer">
                            {children}
                        </a>
                    ),
                    'spoiler-tag': ({ children }) => <Spoiler>{children}</Spoiler>,
                    'mention-tag': ({ username, children }) => (
                        <MentionLink href={`/u/${username}`}>
                            {children}
                        </MentionLink>
                    ),
                }}
            >
                {normalized}
            </ReactMarkdown>
        </Container>
    );
}
