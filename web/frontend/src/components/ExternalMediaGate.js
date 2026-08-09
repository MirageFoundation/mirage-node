import React, { useState } from 'react';
import styled from 'styled-components';
import { classifyMediaUrl } from '../utils/mediaPolicy';

const Gate = styled.div`
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding: 12px;
    border: 1px dashed ${props => props.theme?.colors?.border || '#888'};
    border-radius: 8px;
    background: ${props => props.theme?.colors?.surface || 'transparent'};
    color: ${props => props.theme?.colors?.text || 'inherit'};
    font-size: 0.9rem;
    max-width: 100%;
`;

const Host = styled.code`
    font-size: 0.85em;
    word-break: break-all;
`;

const LoadBtn = styled.button`
    cursor: pointer;
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid ${props => props.theme?.colors?.border || '#888'};
    background: ${props => props.theme?.colors?.buttonBg || 'transparent'};
    color: inherit;
    font: inherit;
`;

/**
 * Network-silent gate for non-allowlisted media.
 * Children are not mounted until the user clicks Load.
 *
 * @param {{ url: string, mediaType?: string, forceConsent?: boolean, children: (ctx: { url: string, classification: any }) => React.ReactNode }} props
 */
export default function ExternalMediaGate({ url, mediaType = 'media', forceConsent = false, children }) {
    const classification = classifyMediaUrl(url);
    const needsConsent = forceConsent || !classification.autoLoad;
    const [consented, setConsented] = useState(false);

    if (!classification.ok) {
        return (
            <Gate data-media-gate="invalid">
                <span>Blocked {mediaType}</span>
            </Gate>
        );
    }

    if (needsConsent && !consented) {
        const host = classification.hostname || 'unknown host';
        return (
            <Gate data-media-gate="pending" data-media-host={host}>
                <span>External {mediaType} from <Host>{host}</Host></span>
                <LoadBtn
                    type="button"
                    onClick={() => {
                        try {
                            console.debug('[MediaPolicy] click-to-load', {
                                hostname: host,
                                provider: classification.provider,
                            });
                        } catch (_) { /* noop */ }
                        setConsented(true);
                    }}
                >
                    Load {mediaType}
                </LoadBtn>
            </Gate>
        );
    }

    return typeof children === 'function'
        ? children({ url, classification })
        : children;
}
