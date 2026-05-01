import React from "react";
import styled from "styled-components";
import {
    HiOutlineEyeSlash,
    HiOutlineExclamationCircle,
    HiOutlineExclamationTriangle,
} from "react-icons/hi2";

/**
 * ContentTagBadge — shared content-warning pill used across the
 * `default` theme (CardView, ListFeedView, ViewPostView, DiscoverView).
 *
 * The visual treatment mirrors the mirage mobile app's
 * `src/components/atoms/content-warning-badge.tsx` (`MirageFoundation/mirage-mobile-app`):
 * a small icon + capitalized label inside a soft-tinted pill with a
 * full-color border. One config map, one component, used everywhere so
 * the warning chip stays consistent on web + mobile.
 */

export const TAG_CONFIG = {
    sensitive: { label: "Sensitive", color: "#d97706", Icon: HiOutlineExclamationCircle },
    adult:     { label: "Adult",     color: "#dc2626", Icon: HiOutlineEyeSlash },
    violence:  { label: "Violence",  color: "#dc2626", Icon: HiOutlineExclamationTriangle },
};

const DEFAULT_TAG = { label: "", color: "#475569", Icon: HiOutlineExclamationCircle };

export const getTagConfig = (tag) => {
    if (!tag) return DEFAULT_TAG;
    return TAG_CONFIG[tag] || { ...DEFAULT_TAG, label: String(tag) };
};

const Pill = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: ${({ $size }) => ($size === "md" ? "2px 6px" : "1px 5px")};
    border-radius: 6px;
    background: ${({ $color }) => `${$color}1F`};
    color: ${({ $color }) => $color};
    font-size: 0.62rem;
    font-weight: 600;
    line-height: 1.2;
    border: 0.5px solid ${({ $color }) => $color};
    vertical-align: middle;

    svg {
        width: 11px;
        height: 11px;
        flex-shrink: 0;
    }
`;

/**
 * Render a content-warning badge.
 * @param {string} tag       Normalized tag key (e.g. "sensitive", "adult", "violence").
 * @param {"sm"|"md"} size   Visual size variant. Defaults to "sm" (feed/compact).
 */
function ContentTagBadge({ tag, size = "sm", className }) {
    if (!tag) return null;
    const cfg = getTagConfig(tag);
    if (!cfg.label) return null;
    const Icon = cfg.Icon;
    return (
        <Pill $color={cfg.color} $size={size} title={cfg.label} className={className}>
            <Icon aria-hidden="true" />
            {cfg.label}
        </Pill>
    );
}

export default ContentTagBadge;
