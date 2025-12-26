import React, { useState, useEffect } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation } from 'react-router-dom';
import Storage from "../utils/Storage";
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import MobileHeader from '../components/MobileHeader';
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from '../styled/Layout';

const Row = styled.div`
    display: grid;
    grid-template-columns: 14rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: start;
    margin: 0.4rem 0;
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
    }
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    padding-top: 0.7rem;
    @media (max-width: 1000px) {
        padding-top: 0;
        margin-bottom: 0.1rem;
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const ThemeSelect = styled.select`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.5rem 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.85rem;
    width: 100%;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
`;

const ExplanationText = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    margin-top: 0.25rem;
    font-style: italic;
    line-height: 1.4;
`;

const CheckboxLabel = styled.label`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.85rem;
`;

const CheckboxLabelMultiline = styled.label`
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.85rem;
`;

const HelperText = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.75rem;
`;


export default function SettingsView({ state }) {
    const location = useLocation();

    const [themeMode, setThemeMode] = useState(() => {
        try {
            return Storage.load('theme_mode', 'time');
        } catch (_) {
            return 'system';
        }
    });
    const [collapseThreshold, setCollapseThreshold] = useState(() => {
        try {
            const v = Storage.load('comment_auto_collapse_threshold', -5);
            const n = Number(v);
            return Number.isFinite(n) ? n : -5;
        } catch (_) {
            return -5;
        }
    });
    const [sidebarTopicsLimit, setSidebarTopicsLimit] = useState(() => {
        try {
            const v = Storage.load('sidebar_topics_limit', 10);
            const n = Number(v);
            return Number.isFinite(n) ? n : 10;
        } catch (_) {
            return 10;
        }
    });
    const [sidebarPeopleLimit, setSidebarPeopleLimit] = useState(() => {
        try {
            const v = Storage.load('sidebar_people_limit', 10);
            const n = Number(v);
            return Number.isFinite(n) ? n : 10;
        } catch (_) {
            return 10;
        }
    });
    const [hideDownvotedPosts, setHideDownvotedPosts] = useState(() => {
        try {
            const val = Storage.load('hide_downvoted_posts', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [blurSensitiveMedia, setBlurSensitiveMedia] = useState(() => {
        try {
            const val = Storage.load('blur_sensitive_media', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    // Content tag visibility (default: only sensitive shown, others hidden)
    const [showTagSensitive, setShowTagSensitive] = useState(() => {
        try {
            const val = Storage.load('show_tag_sensitive', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [showTagPorn, setShowTagPorn] = useState(() => {
        try {
            return Storage.load('show_tag_porn', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [showTagViolence, setShowTagViolence] = useState(() => {
        try {
            return Storage.load('show_tag_violence', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [showTagGore, setShowTagGore] = useState(() => {
        try {
            return Storage.load('show_tag_gore', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [showTagDeath, setShowTagDeath] = useState(() => {
        try {
            return Storage.load('show_tag_death', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [fullWidthMode, setFullWidthMode] = useState(() => {
        try {
            return Storage.load('full_width_mode', false) === true;
        } catch (_) {
            return false;
        }
    });

    // Apply full width mode on mount and when it changes
    useEffect(() => {
        const root = document.documentElement;
        if (fullWidthMode) {
            root.style.setProperty('--content-max-width', 'none');
            root.style.setProperty('--feed-max-width', 'none');
        } else {
            root.style.setProperty('--content-max-width', '1240px');
            root.style.setProperty('--feed-max-width', '1000px');
        }
    }, [fullWidthMode]);

    const handleThemeModeChange = (e) => {
        const newMode = e.target.value;
        setThemeMode(newMode);
        Storage.save('theme_mode', newMode);
        // Trigger a custom event that App.js can listen to
        window.dispatchEvent(new CustomEvent('themeModeChanged', { detail: { mode: newMode } }));
    };


    const handleCollapseThresholdChange = (e) => {
        const raw = e.target.value;
        if (raw === '' || raw === '-' || raw === '−') {
            setCollapseThreshold(NaN);
            return;
        }
        const n = Number(raw);
        if (!Number.isFinite(n)) return;
        setCollapseThreshold(n);
        Storage.save('comment_auto_collapse_threshold', n);
    };

    const handleSidebarTopicsLimitChange = (e) => {
        const n = Number(e.target.value);
        if (!Number.isFinite(n)) return;
        setSidebarTopicsLimit(n);
        Storage.save('sidebar_topics_limit', n);
        window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
    };

    const handleSidebarPeopleLimitChange = (e) => {
        const n = Number(e.target.value);
        if (!Number.isFinite(n)) return;
        setSidebarPeopleLimit(n);
        Storage.save('sidebar_people_limit', n);
        window.dispatchEvent(new CustomEvent('sidebarSettingsUpdated'));
    };

    const getThemeExplanation = (mode) => {
        switch (mode) {
            case 'dark':
                return 'Always use dark theme';
            case 'light':
                return 'Always use light theme';
            case 'system':
                return 'Follows system theme preference';
            case 'time':
                return 'Light theme during daytime hours, dark theme at night (based on date & time)';
            default:
                return '';
        }
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Settings | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Settings</ContainerTab>
                        <ContainerBody>
                            <Row>
                                <Label>Theme:</Label>
                                <ValueBox>
                                    <ThemeSelect value={themeMode} onChange={handleThemeModeChange}>
                                        <option value="time">Time-based</option>
                                        <option value="dark">Dark</option>
                                        <option value="light">Light</option>
                                        <option value="system">System</option>
                                    </ThemeSelect>
                                    <ExplanationText>{getThemeExplanation(themeMode)}</ExplanationText>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Full width:</Label>
                                <ValueBox>
                                    <CheckboxLabel>
                                        <input
                                            type="checkbox"
                                            checked={fullWidthMode}
                                            onChange={(e) => {
                                                const val = !!e.target.checked;
                                                setFullWidthMode(val);
                                                Storage.save('full_width_mode', val);
                                            }}
                                            style={{ width: '16px', height: '16px' }}
                                        />
                                        Expand cards to full screen width
                                    </CheckboxLabel>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Show content with tags:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                        <CheckboxLabel>
                                            <input
                                                type="checkbox"
                                                checked={showTagSensitive}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagSensitive(val);
                                                    Storage.save('show_tag_sensitive', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagSensitive: val } }));
                                                }}
                                                style={{ width: '16px', height: '16px' }}
                                            />
                                            Sensitive
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <input
                                                type="checkbox"
                                                checked={showTagPorn}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagPorn(val);
                                                    Storage.save('show_tag_porn', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagPorn: val } }));
                                                }}
                                                style={{ width: '16px', height: '16px' }}
                                            />
                                            Porn
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <input
                                                type="checkbox"
                                                checked={showTagViolence}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagViolence(val);
                                                    Storage.save('show_tag_violence', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagViolence: val } }));
                                                }}
                                                style={{ width: '16px', height: '16px' }}
                                            />
                                            Violence
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <input
                                                type="checkbox"
                                                checked={showTagGore}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagGore(val);
                                                    Storage.save('show_tag_gore', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagGore: val } }));
                                                }}
                                                style={{ width: '16px', height: '16px' }}
                                            />
                                            Gore
                                        </CheckboxLabel>
                                        <CheckboxLabel>
                                            <input
                                                type="checkbox"
                                                checked={showTagDeath}
                                                onChange={(e) => {
                                                    const val = !!e.target.checked;
                                                    setShowTagDeath(val);
                                                    Storage.save('show_tag_death', val);
                                                    window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { showTagDeath: val } }));
                                                }}
                                                style={{ width: '16px', height: '16px' }}
                                            />
                                            Death
                                        </CheckboxLabel>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Blur sensitive media:</Label>
                                <ValueBox>
                                    <CheckboxLabelMultiline>
                                        <input
                                            type="checkbox"
                                            checked={blurSensitiveMedia}
                                            onChange={(e) => {
                                                const val = !!e.target.checked;
                                                setBlurSensitiveMedia(val);
                                                Storage.save('blur_sensitive_media', val);
                                                window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { blurSensitiveMedia: val } }));
                                            }}
                                            style={{ width: '16px', height: '16px', flexShrink: 0, marginTop: '2px' }}
                                        />
                                        Blur tagged sensitive media when the post has images or video.
                                    </CheckboxLabelMultiline>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Auto-collapse:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        <ThemeSelect
                                            value={Number.isFinite(collapseThreshold) ? String(collapseThreshold) : '-5'}
                                            onChange={(e) => handleCollapseThresholdChange({ target: { value: e.target.value } })}
                                            style={{ width: 'auto', minWidth: '5rem' }}
                                        >
                                            <option value="-3">-3</option>
                                            <option value="-5">-5</option>
                                            <option value="-10">-10</option>
                                            <option value="-25">-25</option>
                                            <option value="-50">-50</option>
                                            <option value="0">Never</option>
                                        </ThemeSelect>
                                        <HelperText>
                                            Collapse comments at or below this score.
                                        </HelperText>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Sidebar topics:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        <ThemeSelect
                                            value={String(sidebarTopicsLimit)}
                                            onChange={handleSidebarTopicsLimitChange}
                                            style={{ width: 'auto', minWidth: '5rem' }}
                                        >
                                            <option value="5">5</option>
                                            <option value="10">10</option>
                                            <option value="15">15</option>
                                            <option value="20">20</option>
                                            <option value="50">50</option>
                                            <option value="100">100</option>
                                        </ThemeSelect>
                                        <HelperText>
                                            Topics shown in sidebar before "show more".
                                        </HelperText>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label>Sidebar people:</Label>
                                <ValueBox>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        <ThemeSelect
                                            value={String(sidebarPeopleLimit)}
                                            onChange={handleSidebarPeopleLimitChange}
                                            style={{ width: 'auto', minWidth: '5rem' }}
                                        >
                                            <option value="5">5</option>
                                            <option value="10">10</option>
                                            <option value="15">15</option>
                                            <option value="20">20</option>
                                            <option value="50">50</option>
                                            <option value="100">100</option>
                                        </ThemeSelect>
                                        <HelperText>
                                            People shown in sidebar before "show more".
                                        </HelperText>
                                    </div>
                                </ValueBox>
                            </Row>

                            <Row>
                                <Label style={{ whiteSpace: 'normal' }}>Hide posts you downvote:</Label>
                                <ValueBox>
                                    <CheckboxLabelMultiline>
                                        <input
                                            type="checkbox"
                                            checked={hideDownvotedPosts}
                                            onChange={(e) => {
                                                const val = !!e.target.checked;
                                                setHideDownvotedPosts(val);
                                                Storage.save('hide_downvoted_posts', val);
                                                window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { hideDownvotedPosts: val } }));
                                            }}
                                            style={{ width: '16px', height: '16px', flexShrink: 0, marginTop: '2px' }}
                                        />
                                        Immediately hide any post you downvote (Home feed only).
                                    </CheckboxLabelMultiline>
                                </ValueBox>
                            </Row>

                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
