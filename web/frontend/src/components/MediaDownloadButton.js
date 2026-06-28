import React from "react";
import styled from "styled-components";
import { getMediaDownloadInfo } from "../utils/media";

const DownloadLink = styled.a`
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 30;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 5px 8px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.68);
    color: #fff;
    font-size: 12px;
    font-weight: 700;
    line-height: 1;
    text-decoration: none;
    box-shadow: 0 1px 6px rgba(0, 0, 0, 0.28);
    opacity: 0.82;
    user-select: none;
    transition: opacity 0.12s ease, background 0.12s ease;

    &:hover,
    &:focus {
        background: rgba(0, 0, 0, 0.84);
        color: #fff;
        opacity: 1;
        text-decoration: none;
    }

    &:focus-visible {
        outline: 2px solid #fff;
        outline-offset: 2px;
    }
`;

export default function MediaDownloadButton({ url, kind }) {
    const info = React.useMemo(() => getMediaDownloadInfo(url, kind), [url, kind]);
    if (!info) return null;

    const stopMediaInteraction = (e) => {
        e.stopPropagation();
    };

    return (
        <DownloadLink
            href={info.href}
            download={info.filename}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Download media"
            title="Download media"
            onClick={stopMediaInteraction}
            onPointerDown={stopMediaInteraction}
        >
            Download
        </DownloadLink>
    );
}
