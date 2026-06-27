import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Navigate } from "react-router-dom";
import Storage from "../../../utils/Storage";
import seedVault from "../../../utils/SeedVault";
import { THEMES } from "../../../registry/theme";
import Sidebar from "../components/Sidebar.js";
import TopBar from "../components/TopBar.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../Layout";
import { useSettings, CheckboxInput, RadioInput } from "../../../logic/useSettings";
const Row = styled.div`
    display: grid;
    grid-template-columns: ${({
    theme
}) => theme.layout.formRowColumns};
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    align-items: ${({
    theme
}) => theme.layout.formRowAlign};
    margin: ${({
    theme
}) => theme.layout.formRowMargin};
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
    }
`;
const Label = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: ${({
    theme
}) => theme.layout.labelWeight};
    font-size: ${({
    theme
}) => theme.layout.labelSize};
    white-space: nowrap;
    padding-top: ${({
    theme
}) => theme.layout.labelPaddingTop};
    @media (max-width: 1000px) {
        padding-top: 0;
        margin-bottom: 0.1rem;
    }
`;
const ValueBox = styled.div`
    background-color: ${({
    theme
}) => theme.layout.containerBg};
    border: ${({
    theme
}) => theme.layout.containerBorder};
    border-bottom: ${({
    theme
}) => theme.layout.containerBorderBottom};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.containerPadding};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;
const ThemeSelect = styled.select`
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    width: 100%;
    cursor: pointer;
    transition: border-color 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: ${({
    theme
}) => theme.colors.focusBorder};
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }
`;
const ExplanationText = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    margin-top: 0.25rem;
    font-style: italic;
    line-height: 1.4;
`;
const CheckboxLabel = styled.label`
    display: inline-grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: ${({
    theme
}) => theme.layout.formRowGap};
    align-items: flex-start;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: ${({
    theme
}) => theme.layout.bodySize};
    line-height: 1.25;
    white-space: normal;
    max-width: 100%;
    cursor: pointer;
    user-select: none;

    &:hover input[type="checkbox"] {
        border-color: ${({
    theme
}) => theme.colors.borderStrong};
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }
`;
const HelperText = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: ${({
    theme
}) => theme.layout.smallSize};
`;
const SecurityBanner = styled.div`
    background-color: ${({
    theme
}) => theme.colors.warningBg};
    border: 1px solid ${({
    theme
}) => theme.colors.warningBorder};
    border-radius: ${({
    theme
}) => theme.layout.bannerRadius};
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    font-size: ${({
    theme
}) => theme.layout.bannerSize};
    line-height: 1.4;
    color: ${({
    theme
}) => theme.colors.text};
`;
const RadioGroup = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({
    theme
}) => theme.layout.formRowGap};
`;
const RadioLabel = styled.label`
    display: inline-grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: ${({
    theme
}) => theme.layout.formRowGap};
    align-items: flex-start;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: ${({
    theme
}) => theme.layout.bodySize};
    line-height: 1.25;
    cursor: ${({
    $disabled
}) => $disabled ? 'not-allowed' : 'pointer'};
    opacity: ${({
    $disabled
}) => $disabled ? 0.45 : 1};
    user-select: none;
`;
const RadioDescription = styled.span`
    display: block;
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    color: ${({
    theme
}) => theme.colors.subtleText};
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
    max-width: 220px;
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    color: ${({
    theme
}) => theme.colors.text};
    box-sizing: border-box;

    &:focus {
        outline: none;
        border-color: ${({
    theme
}) => theme.colors.focusBorder};
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }
`;
const SmallButton = styled.button`
    padding: ${({
    theme
}) => theme.layout.buttonPadding};
    font-size: ${({
    theme
}) => theme.layout.buttonSize};
    font-weight: 600;
    cursor: pointer;
    border: none;
    border-radius: ${({
    theme
}) => theme.layout.buttonRadius};
    background: ${({
    theme
}) => theme.colors.accent};
    color: ${({
    theme
}) => theme.colors.bg};
    transition: background 0.15s ease;
    white-space: nowrap;

    &:hover:not(:disabled) {
        background: ${({
    theme
}) => theme.colors.accentHover};
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;
const DangerButton = styled(SmallButton)`
    background: ${({
    theme
}) => theme.colors.danger};

    &:hover:not(:disabled) {
        background: ${({
    theme
}) => theme.colors.danger};
    }
`;
const DangerInput = styled.input`
    flex: 1;
    min-width: 160px;
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    color: ${({
    theme
}) => theme.colors.text};
    box-sizing: border-box;

    &:focus {
        outline: none;
        border-color: ${({
    theme
}) => theme.colors.danger};
        box-shadow: ${({
    theme
}) => theme.layout.focusRing};
    }
`;
const DangerRow = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
`;
const DangerNotice = styled.div`
    color: ${({
    theme
}) => theme.colors.danger};
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    line-height: 1.4;
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
`;
const SecurityError = styled.div`
    color: ${({
    theme
}) => theme.colors.danger};
    font-size: 0.72rem;
    margin-top: 0.35rem;
`;
const SecuritySuccess = styled.div`
    background-color: ${({
    theme
}) => theme.colors.successBg};
    border: 1px solid ${({
    theme
}) => theme.colors.successBorder};
    border-radius: ${({
    theme
}) => theme.layout.bannerRadius};
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
    margin-top: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    color: ${({
    theme
}) => theme.colors.success};
    font-size: ${({
    theme
}) => theme.layout.bannerSize};
    display: flex;
    align-items: center;
    gap: 0.4rem;
`;
const SeedGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.4rem;
    max-width: 100%;
    margin: 0.5rem 0;
    padding: 0.75rem;
    background-color: ${({
    theme
}) => theme.colors.panel};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 4px;
    position: relative;
    box-sizing: border-box;

    @media (max-width: 1000px) {
        grid-template-columns: repeat(3, 1fr);
        padding: 0.5rem;
        gap: 0.3rem;
    }
`;
const SeedWord = styled.div`
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 4px;
    padding: 0.3rem 0.2rem;
    text-align: left;
    font-size: 0.75rem;
    color: ${({
    theme
}) => theme.colors.text};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    display: flex;
    align-items: center;
    gap: 0.2rem;
    white-space: nowrap;
    word-break: normal;
    overflow-wrap: normal;

    &:before {
        content: attr(data-index);
        color: ${({
    theme
}) => theme.colors.subtleText};
        font-size: 0.5rem;
        min-width: 12px;
        font-weight: bold;
    }

    @media (max-width: 400px) {
        font-size: 0.7rem;
        padding: 0.25rem 0.15rem;
        gap: 0.1rem;
        &:before {
            font-size: 0.45rem;
            min-width: 10px;
        }
    }
`;
const SeedWarning = styled.div`
    color: ${({
    theme
}) => theme.colors.warning};
    font-size: 0.7rem;
    line-height: 1.35;
    margin-bottom: 0.5rem;
`;
const GhostButton = styled(SmallButton)`
    background: transparent;
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    color: ${({
    theme
}) => theme.colors.muted};

    &:hover:not(:disabled) {
        background: transparent;
        border-color: ${({
    theme
}) => theme.colors.borderStrong};
    }
`;
const Divider = styled.hr`
    border: none;
    border-top: 1px solid ${({
    theme
}) => theme.colors.border};
    margin: ${({
    theme
}) => theme.layout.dividerMargin};
`;
export default function SettingsView({
    state
}) {
    const {
        location,
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
        analyticsConsent,
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
        handleAnalyticsToggle,
        handleCollapseThresholdChange,
        handleSidebarTopicsLimitChange,
        handleSidebarPeopleLimitChange,
        getThemeExplanation,
        handleDeleteAccount
    } = useSettings({
        state
    });
    if (!state.publicKey) {
        return <Navigate to="/login" replace />;
    }
    return <ContentGrid>
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
                                <ThemeSelect value={themeId} onChange={handleThemeIdChange}>
                                    {Object.values(THEMES).map(t => <option key={t.id} value={t.id}>{t.label} — {t.description}</option>)}
                                </ThemeSelect>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label>Theme mode:</Label>
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

                        {inviteCodesRequired && <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Referral links:</Label>
                            <ValueBox>
                                <CheckboxLabel>
                                    <CheckboxInput checked={referralPrecheckEnabled} disabled={referralPrecheckBusy} onChange={e => handleReferralPrecheckToggle(!!e.target.checked)} />
                                    Enable referral links for my account
                                </CheckboxLabel>
                                <ExplanationText>
                                    Lets users sign up via your personal link instead of sharing invite codes directly. Anyone with the link can use your codes, so leave this off if you want to hand them out manually.
                                </ExplanationText>
                                {referralPrecheckError && <SecurityError>{referralPrecheckError}</SecurityError>}
                                {referralPrecheckSuccess && <SecuritySuccess>{referralPrecheckSuccess}</SecuritySuccess>}
                            </ValueBox>
                        </Row>}

                        <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Usage analytics:</Label>
                            <ValueBox>
                                <CheckboxLabel>
                                    <CheckboxInput checked={analyticsConsent} onChange={e => handleAnalyticsToggle(!!e.target.checked)} />
                                    Share anonymous usage data to help improve Mirage
                                </CheckboxLabel>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Show content with tags:</Label>
                            <ValueBox>
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.5rem'
                                }}>
                                    <CheckboxLabel>
                                        <CheckboxInput checked={showTagSensitive} onChange={e => {
                                            const val = !!e.target.checked;
                                            setShowTagSensitive(val);
                                            Storage.save('show_tag_sensitive', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                                detail: {
                                                    showTagSensitive: val
                                                }
                                            }));
                                        }} />
                                        Sensitive
                                    </CheckboxLabel>
                                    <CheckboxLabel>
                                        <CheckboxInput checked={showTagAdult} onChange={e => {
                                            const val = !!e.target.checked;
                                            setShowTagAdult(val);
                                            Storage.save('show_tag_adult', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                                detail: {
                                                    showTagAdult: val
                                                }
                                            }));
                                        }} />
                                        Adult
                                    </CheckboxLabel>
                                    <CheckboxLabel>
                                        <CheckboxInput checked={showTagViolence} onChange={e => {
                                            const val = !!e.target.checked;
                                            setShowTagViolence(val);
                                            Storage.save('show_tag_violence', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                                detail: {
                                                    showTagViolence: val
                                                }
                                            }));
                                        }} />
                                        Violence
                                    </CheckboxLabel>
                                    <CheckboxLabel>
                                        <CheckboxInput checked={showTagGore} onChange={e => {
                                            const val = !!e.target.checked;
                                            setShowTagGore(val);
                                            Storage.save('show_tag_gore', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                                detail: {
                                                    showTagGore: val
                                                }
                                            }));
                                        }} />
                                        Gore
                                    </CheckboxLabel>
                                    <CheckboxLabel>
                                        <CheckboxInput checked={showTagDeath} onChange={e => {
                                            const val = !!e.target.checked;
                                            setShowTagDeath(val);
                                            Storage.save('show_tag_death', val);
                                            window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                                detail: {
                                                    showTagDeath: val
                                                }
                                            }));
                                        }} />
                                        Death
                                    </CheckboxLabel>
                                </div>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Blur sensitive media:</Label>
                            <ValueBox>
                                <CheckboxLabel>
                                    <CheckboxInput checked={blurSensitiveMedia} onChange={e => {
                                        const val = !!e.target.checked;
                                        setBlurSensitiveMedia(val);
                                        Storage.save('blur_sensitive_media', val);
                                        window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                            detail: {
                                                blurSensitiveMedia: val
                                            }
                                        }));
                                    }} />
                                    Blur tagged sensitive media (images/videos)
                                </CheckboxLabel>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label>Auto-collapse:</Label>
                            <ValueBox>
                                <div style={{
                                    display: 'flex',
                                    gap: '0.5rem',
                                    alignItems: 'center'
                                }}>
                                    <ThemeSelect value={Number.isFinite(collapseThreshold) ? String(collapseThreshold) : '-5'} onChange={e => handleCollapseThresholdChange({
                                        target: {
                                            value: e.target.value
                                        }
                                    })} style={{
                                        width: 'auto',
                                        minWidth: '5rem'
                                    }}>
                                        <option value="-3">-3</option>
                                        <option value="-5">-5</option>
                                        <option value="-10">-10</option>
                                        <option value="-25">-25</option>
                                        <option value="-50">-50</option>
                                        <option value="0">Never</option>
                                    </ThemeSelect>
                                    <HelperText>
                                        Collapse comments at or below this score
                                    </HelperText>
                                </div>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label>Sidebar topics:</Label>
                            <ValueBox>
                                <div style={{
                                    display: 'flex',
                                    gap: '0.5rem',
                                    alignItems: 'center'
                                }}>
                                    <ThemeSelect value={String(sidebarTopicsLimit)} onChange={handleSidebarTopicsLimitChange} style={{
                                        width: 'auto',
                                        minWidth: '5rem'
                                    }}>
                                        <option value="5">5</option>
                                        <option value="10">10</option>
                                        <option value="15">15</option>
                                        <option value="20">20</option>
                                        <option value="50">50</option>
                                        <option value="100">100</option>
                                    </ThemeSelect>
                                    <HelperText>
                                        Topics shown in sidebar before "show more"
                                    </HelperText>
                                </div>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label>Sidebar users:</Label>
                            <ValueBox>
                                <div style={{
                                    display: 'flex',
                                    gap: '0.5rem',
                                    alignItems: 'center'
                                }}>
                                    <ThemeSelect value={String(sidebarPeopleLimit)} onChange={handleSidebarPeopleLimitChange} style={{
                                        width: 'auto',
                                        minWidth: '5rem'
                                    }}>
                                        <option value="5">5</option>
                                        <option value="10">10</option>
                                        <option value="15">15</option>
                                        <option value="20">20</option>
                                        <option value="50">50</option>
                                        <option value="100">100</option>
                                    </ThemeSelect>
                                    <HelperText>
                                        Users shown in sidebar before "show more"
                                    </HelperText>
                                </div>
                            </ValueBox>
                        </Row>

                        <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Hide posts you downvote:</Label>
                            <ValueBox>
                                <CheckboxLabel>
                                    <CheckboxInput checked={hideDownvotedPosts} onChange={e => {
                                        const val = !!e.target.checked;
                                        setHideDownvotedPosts(val);
                                        Storage.save('hide_downvoted_posts', val);
                                        window.dispatchEvent(new CustomEvent('settingsUpdated', {
                                            detail: {
                                                hideDownvotedPosts: val
                                            }
                                        }));
                                    }} />
                                    Immediately hide downvoted posts
                                </CheckboxLabel>
                            </ValueBox>
                        </Row>

                        <Divider />

                        {seedMode === 'insecure' && state.publicKey && <SecurityBanner>
                            Your recovery phrase is stored unencrypted in this browser. Consider enabling password or passkey protection below.
                        </SecurityBanner>}

                        <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Seed phrase storage:</Label>
                            <ValueBox>
                                <RadioGroup>
                                    <RadioLabel>
                                        <RadioInput name="seed_mode" value="insecure" checked={seedMode === 'insecure' && secPending !== 'password'} onChange={() => handleModeSelect('insecure')} disabled={secBusy} />
                                        <span>
                                            Unencrypted (default)
                                            <RadioDescription>Fastest. Seed stored in plaintext in browser storage.</RadioDescription>
                                        </span>
                                    </RadioLabel>
                                    {secSuccess && seedMode === 'insecure' && <SecuritySuccess>{secSuccess}</SecuritySuccess>}

                                    <RadioLabel>
                                        <RadioInput name="seed_mode" value="password" checked={seedMode === 'password' || secPending === 'password'} onChange={() => handleModeSelect('password')} disabled={secBusy} />
                                        <span>
                                            Password encrypted
                                            <RadioDescription>Seed encrypted with a password you choose. Enter it once per session to unlock.</RadioDescription>
                                        </span>
                                    </RadioLabel>

                                    {secPending === 'password' && <div style={{
                                        paddingLeft: '1.3rem'
                                    }}>
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
                                    {secSuccess && seedMode === 'password' && <SecuritySuccess>{secSuccess}</SecuritySuccess>}

                                    <RadioLabel>
                                        <RadioInput name="seed_mode" value="memory" checked={seedMode === 'memory'} onChange={() => handleModeSelect('memory')} disabled={secBusy} />
                                        <span>
                                            Memory only
                                            <RadioDescription>Most secure. You must re-enter your 12-word phrase each session.</RadioDescription>
                                        </span>
                                    </RadioLabel>
                                    {secSuccess && seedMode === 'memory' && <SecuritySuccess>{secSuccess}</SecuritySuccess>}

                                    <RadioLabel $disabled={!prfSupported}>
                                        <RadioInput name="seed_mode" value="passkey" checked={seedMode === 'passkey'} onChange={() => handleModeSelect('passkey')} disabled={secBusy || !prfSupported} />
                                        <span>
                                            Passkey (Touch ID / Face ID / Security Key)
                                            <RadioDescription>
                                                {prfSupported ? 'Seed encrypted with your passkey. Authenticate to unlock each session.' : 'Requires Chrome, Edge, or Safari. Not supported in Firefox yet.'}
                                            </RadioDescription>
                                        </span>
                                    </RadioLabel>
                                    {secSuccess && seedMode === 'passkey' && <SecuritySuccess>{secSuccess}</SecuritySuccess>}
                                </RadioGroup>

                                {secError && secPending !== 'password' && <SecurityError>{secError}</SecurityError>}
                            </ValueBox>
                        </Row>

                        {state.publicKey && <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Recovery phrase:</Label>
                            <ValueBox>
                                {!seedRevealed ? <>
                                    <SmallButton onClick={() => {
                                        const s = seedVault.getSeed();
                                        if (!s) {
                                            setSecError('No seed phrase available. Please sign in first.');
                                            return;
                                        }
                                        setSeedRevealed(true);
                                        setSeedCopied(false);
                                    }}>
                                        Reveal Recovery Phrase
                                    </SmallButton>
                                    <ExplanationText>Show your 12-word recovery phrase so you can back it up.</ExplanationText>
                                </> : <>
                                    <SeedWarning>
                                        Anyone with this phrase can access your account. Do not share it. It will be hidden automatically after 60 seconds.
                                    </SeedWarning>
                                    <SeedGrid>
                                        {(seedVault.getSeed() || '').split(' ').map((word, i) => <SeedWord key={i} data-index={i + 1}>
                                            {word}
                                        </SeedWord>)}
                                    </SeedGrid>
                                    <div style={{
                                        display: 'flex',
                                        gap: '0.5rem',
                                        marginTop: '0.35rem'
                                    }}>
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
                                    </div>
                                </>}
                            </ValueBox>
                        </Row>}

                        <Divider />

                        <Row>
                            <Label style={{
                                whiteSpace: 'normal'
                            }}>Delete account:</Label>
                            <ValueBox>
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
                                {deleteSuccess && <SecuritySuccess>{deleteSuccess}</SecuritySuccess>}
                            </ValueBox>
                        </Row>

                    </ContainerBody>
                </TabbedContainer>
            </ModernPostFeed>
        </div>
    </ContentGrid>;
}
