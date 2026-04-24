import { useState, useCallback } from "react";
import { Helmet } from "react-helmet-async";
import styled, { keyframes } from "styled-components";
import { Navigate } from "react-router-dom";
import Storage from "../../../utils/Storage";
import seedVault from "../../../utils/SeedVault";
import { THEMES } from "../../../registry/theme";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { useSettings, RadioInput } from "../../../logic/useSettings";

const SettingsWrap = styled.div`
    width: 90%;
    max-width: 960px;
    margin: -0.75rem auto 0;

    @media (max-width: 1000px) {
        width: 100%;
        max-width: none;
        margin-top: -0.5rem;
    }

    /* Large displays: above ~1500px the shell drops its centered
     * max-width cap and pins the sidebar to the left viewport edge.
     * margin: auto then centers the column within Main (which is
     * offset right by the sidebar), not within the viewport — content
     * visually sits ~128px right of the true viewport center.
     *
     * Override with a viewport-relative margin so the column is
     * centered against the viewport regardless of sidebar state.
     *
     * Offset = sidebar column + divider + Main left padding:
     *   sidebar visible:  240 + 17 + 16 = 273px
     *   sidebar hidden:    0 + 17 + 16 =  33px
     *
     * Applied only at breakpoints where the calc stays non-negative
     * (content fits viewport-centered). Below these widths we fall
     * back to margin: auto. */
    /* Sidebar HIDDEN: 960px content + 33 offset needs vw >= ~1026px.
     * Apply from 1050px so the column is truly viewport-centered
     * across the full desktop range, not just 1600px+. */
    @media (min-width: 1050px) {
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 480px - 33px);
            margin-right: auto;
        }
    }

    /* Sidebar VISIBLE: 960px content + 273 offset needs vw >= ~1506px.
     * Below this the column can't be viewport-centered without
     * overlapping the sidebar, so margin: auto (Main-centered) stays. */
    @media (min-width: 1600px) {
        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 480px - 273px);
            margin-right: auto;
        }
    }

    @media (min-width: 1900px) {
        max-width: 1100px;

        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 550px - 273px);
        }
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 550px - 33px);
        }
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.75rem;
    padding: 0.5rem 1rem;

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

const HeaderTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.65rem 1rem 0.35rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;

    @media (max-width: 600px) {
        padding: 0.65rem 0 0.35rem;
    }
`;

const SectionDivider = styled.div`
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    width: 100%;
`;

const SettingRow = styled.div`
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.55rem 1rem;

    @media (max-width: 600px) {
        flex-direction: column;
        gap: 0.4rem;
        padding: 0.5rem 0;
    }
`;

const SettingLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 500;
    white-space: nowrap;
    padding-top: 0.15rem;
    flex-shrink: 0;

    @media (max-width: 600px) {
        padding-top: 0;
    }
`;

const SettingControl = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
`;

const ExplanationText = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    margin-top: 0.15rem;
    font-style: italic;
    line-height: 1.4;
`;



const SecurityBanner = styled.div`
    background-color: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.25);
    border-radius: 8px;
    padding: 0.5rem 1rem;
    margin: 0.25rem 1rem 0.35rem;
    font-size: 0.65rem;
    line-height: 1.4;
    color: ${({ theme }) => theme.colors.text};

    @media (max-width: 600px) {
        margin: 0.25rem 0 0.35rem;
    }
`;

const RadioGroup = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
`;

const RadioLabel = styled.label`
    display: inline-grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.35rem;
    align-items: flex-start;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    line-height: 1.25;
    cursor: ${({ $disabled }) => $disabled ? 'not-allowed' : 'pointer'};
    opacity: ${({ $disabled }) => $disabled ? 0.45 : 1};
    user-select: none;
`;

const RadioDescription = styled.span`
    display: block;
    font-size: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-style: italic;
    margin-top: 0.1rem;
`;

const InlinePasswordRow = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-top: 0.5rem;
    flex-wrap: wrap;
`;

const PasswordInput = styled.input`
    flex: 1;
    min-width: 120px;
    max-width: 260px;
    box-sizing: border-box;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    background: ${({ theme }) => theme.colors.inputBackground};
    color: ${({ theme }) => theme.colors.text};
    padding: 0.35rem 0.6rem;
    font: inherit;
    font-size: 0.72rem;
    line-height: 1.3;
    transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.hoverBg || theme.colors.inputBackground};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
        background: ${({ theme }) => theme.colors.hoverBg || theme.colors.inputBackground};
    }

    &:disabled {
        opacity: 0.65;
        cursor: not-allowed;
    }
`;

const SmallButton = styled.button`
    padding: 0.35rem 0.75rem;
    font-size: 0.72rem;
    line-height: 1.3;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid ${({ theme }) => theme.colors.followBtnBg};
    border-radius: 6px;
    background: ${({ theme }) => theme.colors.followBtnBg};
    color: #fff;
    font-family: inherit;
    transition: background 0.15s ease, border-color 0.15s ease;
    white-space: nowrap;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.followBtnBgHover};
        border-color: ${({ theme }) => theme.colors.followBtnBgHover};
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const DangerButton = styled(SmallButton)`
    background: ${({ theme }) => theme.colors.voteDown};
    border-color: ${({ theme }) => theme.colors.voteDown};

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.voteDownHover || theme.colors.voteDown};
        border-color: ${({ theme }) => theme.colors.voteDownHover || theme.colors.voteDown};
    }
`;

const DangerInput = styled.input`
    flex: 1;
    min-width: 160px;
    padding: 0.3rem 0.5rem;
    font-size: 0.7rem;
    background-color: ${({ theme }) => theme.colors.inputBackground};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    color: ${({ theme }) => theme.colors.text};
    box-sizing: border-box;
    font-family: inherit;

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.voteDown};
    }
`;

const DangerRow = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
`;

const DangerNotice = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    line-height: 1.4;
    margin-bottom: 0.35rem;
`;

const SecurityError = styled.div`
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.65rem;
    margin-top: 0.35rem;
`;

const SecuritySuccess = styled.div`
    background-color: ${({ theme }) => theme.colors.buttonSuccessBg};
    border: 1px solid ${({ theme }) => `${theme.colors.voteUp}40`};
    border-radius: 8px;
    padding: 0.35rem 0.65rem;
    margin-top: 0.35rem;
    color: ${({ theme }) => theme.colors.voteUp};
    font-size: 0.65rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
`;

const SettingsTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const SettingsShellBody = styled(ContainerBody)`
    padding: 0.35rem 0 0.75rem;
    border: none;
    border-radius: 0;
`;

const ClickableSettingRow = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    width: 100%;
    padding: 0.55rem 1rem;
    border: none;
    background: transparent;
    cursor: pointer;
    font-family: inherit;
    text-align: left;

    &:hover .chevron-pill {
        background: ${({ theme }) => theme.colors.surface3};
    }

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

const ClickableRowLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
`;

const ClickableRowRight = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
`;

const ClickableRowValue = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const ChevronPill = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 28px;
    border-radius: 999px;
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
    transition: background 0.15s ease;

    svg {
        width: 16px;
        height: 16px;
    }
`;

const fadeIn = keyframes`
    from { opacity: 0; }
    to { opacity: 1; }
`;

const slideUp = keyframes`
    from { transform: translateY(12px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
`;

const ModalOverlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: ${({ theme }) => theme.colors.overlay};
    display: flex;
    align-items: center;
    justify-content: center;
    animation: ${fadeIn} 0.15s ease;
    padding: 1rem;
`;

const ModalPanel = styled.div`
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    width: 100%;
    max-width: 360px;
    max-height: 70vh;
    overflow-y: auto;
    animation: ${slideUp} 0.2s ease;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
`;

const ModalHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const ModalTitle = styled.div`
    font-size: 0.8rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
`;

const ModalClose = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: none;
    border: none;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    padding: 0;
    border-radius: 999px;
    transition: color 0.12s ease, background 0.12s ease;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.surface3};
    }

    svg {
        width: 16px;
        height: 16px;
    }
`;

const ModalOption = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    background: ${({ $active, theme }) => $active ? theme.colors.sidebarItemActiveBg : 'transparent'};
    border: none;
    padding: 0.6rem 1rem;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    transition: background 0.12s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const ModalOptionCheck = styled.span`
    color: ${({ theme }) => theme.colors.focusBlue};
    font-size: 0.85rem;
    font-weight: 700;
    flex-shrink: 0;
`;

const ModalOptionSub = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-top: 0.1rem;
`;

function OptionModal({ title, options, value, onChange, onClose }) {
    return <ModalOverlay onClick={onClose}>
        <ModalPanel onClick={e => e.stopPropagation()}>
            <ModalHeader>
                <ModalTitle>{title}</ModalTitle>
                <ModalClose onClick={onClose}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg></ModalClose>
            </ModalHeader>
            <div>
                {options.map(opt => <ModalOption
                    key={opt.value}
                    $active={opt.value === value}
                    onClick={() => { onChange(opt.value); onClose(); }}
                >
                    <div>
                        {opt.label}
                        {opt.sub && <ModalOptionSub>{opt.sub}</ModalOptionSub>}
                    </div>
                    {opt.value === value && <ModalOptionCheck>✓</ModalOptionCheck>}
                </ModalOption>)}
            </div>
        </ModalPanel>
    </ModalOverlay>;
}

const checkPop = keyframes`
    0% { transform: scale(0.8); }
    50% { transform: scale(1.15); }
    100% { transform: scale(1); }
`;

const ToggleTrack = styled.div`
    width: 42px;
    height: 24px;
    flex: 0 0 42px;
    border-radius: 12px;
    background: ${({ $checked, theme }) => $checked ? theme.colors.followBtnBg : theme.colors.surface3};
    position: relative;
    cursor: pointer;
    transition: background 0.2s ease;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.15);
`;

const ToggleKnob = styled.div`
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #fff;
    position: absolute;
    top: 2px;
    left: ${({ $checked }) => $checked ? '20px' : '2px'};
    transition: left 0.2s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
    animation: ${({ $checked }) => $checked ? checkPop : 'none'} 0.25s ease;
`;

function Toggle({ checked, onChange, disabled }) {
    return <ToggleTrack
        $checked={checked}
        role="switch"
        aria-checked={checked}
        tabIndex={0}
        style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
        onClick={e => {
            if (disabled) return;
            onChange({ target: { checked: !checked } });
        }}
        onKeyDown={e => {
            if (disabled) return;
            if (e.key === ' ' || e.key === 'Enter') {
                e.preventDefault();
                onChange({ target: { checked: !checked } });
            }
        }}
    >
        <ToggleKnob $checked={checked} />
    </ToggleTrack>;
}

const ToggleRow = styled.label`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    cursor: pointer;
    user-select: none;
    padding: 0.15rem 0;
`;

const ToggleLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.3;
`;

const ToggleDesc = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.58rem;
    line-height: 1.35;
    margin-top: 0.1rem;
    font-weight: 400;
`;

const TagsGrid = styled.div`
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;

const TagPill = styled.button`
    display: flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    border: 1px solid ${({ $active, theme }) => $active ? theme.colors.focusBlue : theme.colors.border};
    background: ${({ $active, theme }) => $active ? 'rgba(66, 133, 244, 0.15)' : 'transparent'};
    color: ${({ $active, theme }) => $active ? theme.colors.focusBlue : theme.colors.subtleText};
    font-size: 0.65rem;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    transition: all 0.15s ease;
    user-select: none;

    &:hover {
        border-color: ${({ theme }) => theme.colors.focusBlue};
        color: ${({ theme }) => theme.colors.focusBlue};
    }
`;



const SeedPhraseCard = styled.div`
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 1rem;
    margin-top: 0.25rem;
`;

const SeedWarningBanner = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.25);
    border-radius: 8px;
    padding: 0.5rem 0.65rem;
    margin-bottom: 0.65rem;
    font-size: 0.62rem;
    line-height: 1.4;
    color: #f59e0b;
`;

const SeedGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.35rem;
    margin-bottom: 0.65rem;

    @media (max-width: 600px) {
        grid-template-columns: repeat(3, 1fr);
    }
`;

const SeedWord = styled.div`
    display: flex;
    align-items: center;
    gap: 0.25rem;
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    padding: 0.3rem 0.35rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.72rem;
    color: ${({ theme }) => theme.colors.text};
    white-space: nowrap;
`;

const SeedWordIndex = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.48rem;
    font-weight: 700;
    min-width: 14px;
`;

const SeedActions = styled.div`
    display: flex;
    gap: 0.5rem;
`;

const GhostButton = styled(SmallButton)`
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.text};

    &:hover:not(:disabled) {
        opacity: 1;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const RevealButton = styled(SmallButton)`
    padding: 0.4rem 0.85rem;
    font-size: 0.7rem;
    border-radius: 8px;
`;



export default function SettingsView({ state }) {
    const [openModal, setOpenModal] = useState(null);

    const {
        themeId,
        themeMode,
        collapseThreshold,
        sidebarTopicsLimit,
        sidebarPeopleLimit,
        hideDownvotedPosts,
        setHideDownvotedPosts,
        blurSensitiveMedia,
        setBlurSensitiveMedia,
        showTagSensitive,
        setShowTagSensitive,
        showTagAdult,
        setShowTagAdult,
        showTagViolence,
        setShowTagViolence,
        showTagGore,
        setShowTagGore,
        showTagDeath,
        setShowTagDeath,
        referralPrecheckEnabled,
        referralPrecheckBusy,
        referralPrecheckError,
        referralPrecheckSuccess,
        inviteCodesRequired,
        seedMode,
        prfSupported,
        secPassword,
        setSecPassword,
        secPasswordConfirm,
        setSecPasswordConfirm,
        secPending,
        secError,
        setSecError,
        secSuccess,
        secBusy,
        deleteConfirmText,
        setDeleteConfirmText,
        deleteError,
        setDeleteError,
        deleteSuccess,
        setDeleteSuccess,
        deleteStatus,
        deleteBusy,
        deleteConfirmReady,
        seedRevealed,
        setSeedRevealed,
        seedCopied,
        setSeedCopied,
        commitModeSwitch,
        handleModeSelect,
        handleThemeIdChange,
        handleThemeModeChange,
        handleReferralPrecheckToggle,
        handleCollapseThresholdChange,
        handleSidebarTopicsLimitChange,
        handleSidebarPeopleLimitChange,
        getThemeExplanation,
        handleDeleteAccount
    } = useSettings({ state });

    const closeModal = useCallback(() => setOpenModal(null), []);

    if (!state.publicKey) {
        return <Navigate to="/login" replace />;
    }

    const themeOptions = Object.values(THEMES).map(t => ({ value: t.id, label: t.label, sub: t.description }));
    const modeOptions = [
        { value: 'time', label: 'Time-based', sub: getThemeExplanation('time') },
        { value: 'dark', label: 'Dark' },
        { value: 'light', label: 'Light' },
        { value: 'system', label: 'System', sub: getThemeExplanation('system') },
    ];
    const collapseOptions = [
        { value: '-3', label: '-3' },
        { value: '-5', label: '-5' },
        { value: '-10', label: '-10' },
        { value: '-25', label: '-25' },
        { value: '-50', label: '-50' },
        { value: '0', label: 'Never' },
    ];
    const limitOptions = ['5', '10', '15', '20', '50', '100'].map(v => ({ value: v, label: v }));

    const currentThemeLabel = themeOptions.find(o => o.value === themeId)?.label || themeId;
    const currentModeLabel = modeOptions.find(o => o.value === themeMode)?.label || themeMode;
    const currentCollapseLabel = collapseOptions.find(o => o.value === (Number.isFinite(collapseThreshold) ? String(collapseThreshold) : '-5'))?.label || '-5';

    const tags = [
        { key: 'sensitive', label: 'Sensitive', checked: showTagSensitive, set: setShowTagSensitive, storageKey: 'show_tag_sensitive', eventKey: 'showTagSensitive' },
        { key: 'adult', label: 'Adult', checked: showTagAdult, set: setShowTagAdult, storageKey: 'show_tag_adult', eventKey: 'showTagAdult' },
        { key: 'violence', label: 'Violence', checked: showTagViolence, set: setShowTagViolence, storageKey: 'show_tag_violence', eventKey: 'showTagViolence' },
        { key: 'gore', label: 'Gore', checked: showTagGore, set: setShowTagGore, storageKey: 'show_tag_gore', eventKey: 'showTagGore' },
        { key: 'death', label: 'Death', checked: showTagDeath, set: setShowTagDeath, storageKey: 'show_tag_death', eventKey: 'showTagDeath' },
    ];

    const toggleTag = (tag) => {
        const val = !tag.checked;
        tag.set(val);
        Storage.save(tag.storageKey, val);
        window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { [tag.eventKey]: val } }));
    };

    return <ContentGrid>
        <Helmet>
            <title>Settings | Mirage</title>
        </Helmet>
        <ModernPostFeed>
            <CappedPageColumn>
                <SettingsTabbedContainer>
                    <SettingsShellBody>
                        <SettingsWrap>
                            <HeaderRow>
                                <HeaderTitle>Settings</HeaderTitle>
                            </HeaderRow>
                            <SectionDivider />

                            <SectionHeader>Appearance</SectionHeader>

                            <ClickableSettingRow type="button" onClick={() => setOpenModal('theme')}>
                                <ClickableRowLabel>Theme</ClickableRowLabel>
                                <ClickableRowRight>
                                    <ClickableRowValue>{currentThemeLabel}</ClickableRowValue>
                                    <ChevronPill className="chevron-pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg></ChevronPill>
                                </ClickableRowRight>
                            </ClickableSettingRow>

                            <ClickableSettingRow type="button" onClick={() => setOpenModal('mode')}>
                                <ClickableRowLabel>Mode</ClickableRowLabel>
                                <ClickableRowRight>
                                    <ClickableRowValue>{currentModeLabel}</ClickableRowValue>
                                    <ChevronPill className="chevron-pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg></ChevronPill>
                                </ClickableRowRight>
                            </ClickableSettingRow>

                            <SectionHeader>Content</SectionHeader>

                            <SettingRow>
                                <SettingLabel>Content tags</SettingLabel>
                                <SettingControl>
                                    <TagsGrid>
                                        {tags.map(tag => <TagPill
                                            key={tag.key}
                                            $active={tag.checked}
                                            onClick={() => toggleTag(tag)}
                                            type="button"
                                        >
                                            {tag.label}
                                        </TagPill>)}
                                    </TagsGrid>
                                </SettingControl>
                            </SettingRow>

                            <SettingRow>
                                <SettingControl>
                                    <ToggleRow as="div">
                                        <div>
                                            <ToggleLabel>Blur sensitive media</ToggleLabel>
                                            <ToggleDesc>Blur tagged sensitive images and videos</ToggleDesc>
                                        </div>
                                        <Toggle checked={blurSensitiveMedia} onChange={e => {
                                            const val = !!e.target.checked;
                                            setBlurSensitiveMedia(val);
                                            Storage.save('blur_sensitive_media', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { blurSensitiveMedia: val } }));
                                        }} />
                                    </ToggleRow>
                                </SettingControl>
                            </SettingRow>

                            <ClickableSettingRow type="button" onClick={() => setOpenModal('collapse')}>
                                <ClickableRowLabel>Auto-collapse</ClickableRowLabel>
                                <ClickableRowRight>
                                    <ClickableRowValue>{currentCollapseLabel}</ClickableRowValue>
                                    <ChevronPill className="chevron-pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg></ChevronPill>
                                </ClickableRowRight>
                            </ClickableSettingRow>

                            <SettingRow>
                                <SettingControl>
                                    <ToggleRow as="div">
                                        <div>
                                            <ToggleLabel>Hide downvoted posts</ToggleLabel>
                                            <ToggleDesc>Immediately remove posts you downvote from feed</ToggleDesc>
                                        </div>
                                        <Toggle checked={hideDownvotedPosts} onChange={e => {
                                            const val = !!e.target.checked;
                                            setHideDownvotedPosts(val);
                                            Storage.save('hide_downvoted_posts', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { hideDownvotedPosts: val } }));
                                        }} />
                                    </ToggleRow>
                                </SettingControl>
                            </SettingRow>

                            <SectionHeader>Sidebar</SectionHeader>

                            <ClickableSettingRow type="button" onClick={() => setOpenModal('sidebarTopics')}>
                                <ClickableRowLabel>Topics shown</ClickableRowLabel>
                                <ClickableRowRight>
                                    <ClickableRowValue>{String(sidebarTopicsLimit)}</ClickableRowValue>
                                    <ChevronPill className="chevron-pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg></ChevronPill>
                                </ClickableRowRight>
                            </ClickableSettingRow>

                            <ClickableSettingRow type="button" onClick={() => setOpenModal('sidebarPeople')}>
                                <ClickableRowLabel>People shown</ClickableRowLabel>
                                <ClickableRowRight>
                                    <ClickableRowValue>{String(sidebarPeopleLimit)}</ClickableRowValue>
                                    <ChevronPill className="chevron-pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg></ChevronPill>
                                </ClickableRowRight>
                            </ClickableSettingRow>

                            {inviteCodesRequired && <>
                                <SectionHeader>Referrals</SectionHeader>

                                <SettingRow>
                                    <SettingControl>
                                        <ToggleRow as="div">
                                            <div>
                                                <ToggleLabel>Enable referral links</ToggleLabel>
                                                <ToggleDesc>Lets people sign up via your personal link instead of sharing invite codes directly.</ToggleDesc>
                                            </div>
                                            <Toggle checked={referralPrecheckEnabled} disabled={referralPrecheckBusy} onChange={e => handleReferralPrecheckToggle(!!e.target.checked)} />
                                        </ToggleRow>
                                        {referralPrecheckError && <SecurityError>{referralPrecheckError}</SecurityError>}
                                        {referralPrecheckSuccess && <SecuritySuccess><span>✓</span>{referralPrecheckSuccess}</SecuritySuccess>}
                                    </SettingControl>
                                </SettingRow>
                            </>}

                            <SectionHeader>Security</SectionHeader>

                            {seedMode === 'insecure' && state.publicKey && <SecurityBanner>
                                Your recovery phrase is stored unencrypted in this browser. Consider enabling password or passkey protection below.
                            </SecurityBanner>}

                            <SettingRow>
                                <SettingLabel>Seed storage</SettingLabel>
                                <SettingControl>
                                    <RadioGroup>
                                        <RadioLabel>
                                            <RadioInput name="seed_mode" value="insecure" checked={seedMode === 'insecure' && secPending !== 'password'} onChange={() => handleModeSelect('insecure')} disabled={secBusy} />
                                            <span>
                                                Unencrypted (default)
                                                <RadioDescription>Fastest. Seed stored in plaintext in browser storage.</RadioDescription>
                                            </span>
                                        </RadioLabel>
                                        {secSuccess && seedMode === 'insecure' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}

                                        <RadioLabel>
                                            <RadioInput name="seed_mode" value="password" checked={seedMode === 'password' || secPending === 'password'} onChange={() => handleModeSelect('password')} disabled={secBusy} />
                                            <span>
                                                Password encrypted
                                                <RadioDescription>Seed encrypted with a password you choose. Enter it once per session to unlock.</RadioDescription>
                                            </span>
                                        </RadioLabel>

                                        {secPending === 'password' && <div style={{ paddingLeft: '1.3rem' }}>
                                            <InlinePasswordRow>
                                                <PasswordInput type="password" placeholder="Password" value={secPassword} onChange={e => {
                                                    setSecPassword(e.target.value);
                                                    setSecError('');
                                                }} disabled={secBusy} autoFocus />
                                            </InlinePasswordRow>
                                            <InlinePasswordRow>
                                                <PasswordInput type="password" placeholder="Confirm password" value={secPasswordConfirm} onChange={e => {
                                                    setSecPasswordConfirm(e.target.value);
                                                    setSecError('');
                                                }} disabled={secBusy} onKeyDown={e => {
                                                    if (e.key === 'Enter') {
                                                        e.preventDefault();
                                                        if (secPassword !== secPasswordConfirm) {
                                                            setSecError('Passwords do not match.');
                                                        } else {
                                                            commitModeSwitch('password', secPassword);
                                                        }
                                                    }
                                                }} />
                                                <SmallButton disabled={secBusy || !secPassword.trim()} onClick={() => {
                                                    if (secPassword !== secPasswordConfirm) {
                                                        setSecError('Passwords do not match.');
                                                    } else {
                                                        commitModeSwitch('password', secPassword);
                                                    }
                                                }}>
                                                    {secBusy ? 'Encrypting...' : 'Set Password'}
                                                </SmallButton>
                                            </InlinePasswordRow>
                                            {secError && <SecurityError>{secError}</SecurityError>}
                                        </div>}
                                        {secSuccess && seedMode === 'password' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}

                                        <RadioLabel>
                                            <RadioInput name="seed_mode" value="memory" checked={seedMode === 'memory'} onChange={() => handleModeSelect('memory')} disabled={secBusy} />
                                            <span>
                                                Memory only
                                                <RadioDescription>Most secure. You must re-enter your 12-word phrase each session.</RadioDescription>
                                            </span>
                                        </RadioLabel>
                                        {secSuccess && seedMode === 'memory' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}

                                        <RadioLabel $disabled={!prfSupported}>
                                            <RadioInput name="seed_mode" value="passkey" checked={seedMode === 'passkey'} onChange={() => handleModeSelect('passkey')} disabled={secBusy || !prfSupported} />
                                            <span>
                                                Passkey (Touch ID / Face ID / Security Key)
                                                <RadioDescription>
                                                    {prfSupported ? 'Seed encrypted with your passkey. Authenticate to unlock each session.' : 'Requires Chrome, Edge, or Safari. Not supported in Firefox yet.'}
                                                </RadioDescription>
                                            </span>
                                        </RadioLabel>
                                        {secSuccess && seedMode === 'passkey' && <SecuritySuccess><span>✓</span>{secSuccess}</SecuritySuccess>}
                                    </RadioGroup>

                                    {secError && secPending !== 'password' && <SecurityError>{secError}</SecurityError>}
                                </SettingControl>
                            </SettingRow>

                            {state.publicKey && <SettingRow>
                                <SettingLabel>Recovery phrase</SettingLabel>
                                <SettingControl>
                                    {!seedRevealed ? <>
                                        <RevealButton onClick={() => {
                                            const s = seedVault.getSeed();
                                            if (!s) {
                                                setSecError('No seed phrase available. Please sign in first.');
                                                return;
                                            }
                                            setSeedRevealed(true);
                                            setSeedCopied(false);
                                        }}>
                                            Reveal Recovery Phrase
                                        </RevealButton>
                                        <ExplanationText>Show your 12-word recovery phrase so you can back it up.</ExplanationText>
                                    </> : <SeedPhraseCard>
                                        <SeedWarningBanner>
                                            <span style={{ fontSize: '0.85rem', lineHeight: 1 }}>⚠</span>
                                            <span>Anyone with this phrase can access your account. Do not share it. It will be hidden automatically after 60 seconds.</span>
                                        </SeedWarningBanner>
                                        <SeedGrid>
                                            {(seedVault.getSeed() || '').split(' ').map((word, i) => <SeedWord key={i}>
                                                <SeedWordIndex>{i + 1}</SeedWordIndex>
                                                {word}
                                            </SeedWord>)}
                                        </SeedGrid>
                                        <SeedActions>
                                            <SmallButton onClick={async () => {
                                                try {
                                                    await navigator.clipboard.writeText(seedVault.getSeed() || '');
                                                    setSeedCopied(true);
                                                    setTimeout(() => setSeedCopied(false), 2000);
                                                } catch (_) { }
                                            }}>
                                                {seedCopied ? 'Copied!' : 'Copy'}
                                            </SmallButton>
                                            <GhostButton onClick={() => {
                                                setSeedRevealed(false);
                                                setSeedCopied(false);
                                            }}>
                                                Hide
                                            </GhostButton>
                                        </SeedActions>
                                    </SeedPhraseCard>}
                                </SettingControl>
                            </SettingRow>}

                            <SectionHeader>Account</SectionHeader>

                            <SettingRow>
                                <SettingLabel>Delete account</SettingLabel>
                                <SettingControl>
                                    <DangerNotice>
                                        This submits an account deletion request to the network. Most nodes will honor it, but some may not — full removal cannot be guaranteed.
                                    </DangerNotice>
                                    <DangerRow>
                                        <DangerInput value={deleteConfirmText} onChange={e => {
                                            setDeleteConfirmText(e.target.value);
                                            if (deleteError) setDeleteError('');
                                            if (deleteSuccess) setDeleteSuccess('');
                                        }} onKeyDown={e => {
                                            if (e.key === 'Enter') {
                                                e.preventDefault();
                                                handleDeleteAccount();
                                            }
                                        }} placeholder="Type DELETE to confirm" disabled={deleteBusy} />
                                        <DangerButton disabled={!deleteConfirmReady || deleteBusy} onClick={handleDeleteAccount}>
                                            {deleteStatus || (deleteBusy ? 'Deleting...' : 'Delete account')}
                                        </DangerButton>
                                    </DangerRow>
                                    {deleteError && <SecurityError>{deleteError}</SecurityError>}
                                    {deleteSuccess && <SecuritySuccess><span>✓</span>{deleteSuccess}</SecuritySuccess>}
                                </SettingControl>
                            </SettingRow>

                        </SettingsWrap>
                    </SettingsShellBody>
                </SettingsTabbedContainer>
            </CappedPageColumn>
        </ModernPostFeed>

        {openModal === 'theme' && <OptionModal
            title="Choose Theme"
            options={themeOptions}
            value={themeId}
            onChange={v => handleThemeIdChange({ target: { value: v } })}
            onClose={closeModal}
        />}

        {openModal === 'mode' && <OptionModal
            title="Theme Mode"
            options={modeOptions}
            value={themeMode}
            onChange={v => handleThemeModeChange({ target: { value: v } })}
            onClose={closeModal}
        />}

        {openModal === 'collapse' && <OptionModal
            title="Auto-collapse Threshold"
            options={collapseOptions}
            value={Number.isFinite(collapseThreshold) ? String(collapseThreshold) : '-5'}
            onChange={v => handleCollapseThresholdChange({ target: { value: v } })}
            onClose={closeModal}
        />}

        {openModal === 'sidebarTopics' && <OptionModal
            title="Sidebar Topics Limit"
            options={limitOptions}
            value={String(sidebarTopicsLimit)}
            onChange={v => handleSidebarTopicsLimitChange({ target: { value: v } })}
            onClose={closeModal}
        />}

        {openModal === 'sidebarPeople' && <OptionModal
            title="Sidebar People Limit"
            options={limitOptions}
            value={String(sidebarPeopleLimit)}
            onChange={v => handleSidebarPeopleLimitChange({ target: { value: v } })}
            onClose={closeModal}
        />}
    </ContentGrid>;
}
