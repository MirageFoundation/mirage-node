import React, { useState, useEffect } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import Button from "../components/Button";
import { useNavigate, useLocation, Link } from 'react-router-dom';
import Storage from "../utils/Storage.js";
import Api from '../lib/api';
import * as tx from "../utils/tx";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";
import { getMaxUsernameSize, getMinUsernameSize, getMaxInputLength } from "../config/chainParams";

const BlockingOverlay = styled.div`
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: transparent;
    z-index: 9999;
    cursor: wait;
`

const Centered = styled.div`
    max-width: 500px;
    margin: 0 auto;
    text-align: center;
    padding: 0 1rem;
    box-sizing: border-box;
    
    @media (max-width: 600px) {
        padding: 0 0.5rem;
    }
`

const InputWrapper = styled.div`
    display: flex;
    align-items: center;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2a2e33'};
    border-radius: 6px;
    margin: 0.75rem auto;
    overflow: hidden;
    opacity: ${({ $disabled }) => $disabled ? 0.5 : 1};
    pointer-events: ${({ $disabled }) => $disabled ? 'none' : 'auto'};
    max-width: 100%;
    box-sizing: border-box;

    &:hover, &:focus-within {
        border-color: ${({ $disabled, theme }) => $disabled ? (theme?.colors?.border || '#444') : (theme?.colors?.link || '#667eea')};
    }
`

const InputPrefix = styled.span`
    padding: 0.41rem 0 0.5rem 0.75rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-size: 0.85rem;
    line-height: 1.3;
    user-select: none;
    white-space: nowrap;
`

const StyledInputBox = styled.input`    
    border: none;
    flex: 1;
    min-width: 0;
    width: 100%;
    background-color: transparent;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    text-align: ${({ $hasPrefix }) => $hasPrefix ? 'left' : 'center'};
    resize: none;
    font-size: 0.85rem;
    line-height: 1.3;
    padding: 0.5rem 0.75rem;
    padding-left: ${({ $hasPrefix }) => $hasPrefix ? '0.15rem' : '0.75rem'};
    box-sizing: border-box;
    text-overflow: ellipsis;

    &:focus {
        outline: none;
    }

    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`

const ButtonWrapper = styled.div`
    margin-top: 0.5rem;
`;

const WarningBox = styled.div`
    background-color: rgba(245, 158, 11, 0.1);
    border: 1px solid #f59e0b;
    padding: 0.75rem;
    border-radius: 6px;
    margin-bottom: 0.75rem;
    font-size: 0.8rem;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    text-align: left;
    box-sizing: border-box;
    word-wrap: break-word;
    
    a {
        color: #f59e0b;
        text-decoration: underline;
        font-weight: 600;
        
        &:hover {
            color: #fbbf24;
        }
    }
`;

const SuccessBox = styled.div`
    text-align: center;
    padding: 1.5rem 0;
`;

const SuccessTitle = styled.div`
    font-size: 1.5rem;
    font-weight: bold;
    color: #4ade80;
    margin-bottom: 0.75rem;
`;

const SuccessText = styled.div`
    font-size: 1rem;
    color: ${({ theme }) => theme?.colors?.text || '#ccc'};
    margin-bottom: 0.5rem;
`;

const SuccessSubtext = styled.div`
    font-size: 0.8rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

function ChangeUsernameView({ state }) {
    const navigate = useNavigate();
    const location = useLocation();
    const currentUsername = state?.username || Storage.load('username', '');
    const publicKey = state?.publicKey || Storage.load('publicKey', '');

    const [usernameInput, setUsernameInput] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [buttonStatus, setButtonStatus] = useState("idle");
    const [statusStartTime, setStatusStartTime] = useState(null);
    const [elapsedTime, setElapsedTime] = useState(0);
    const [submitError, setSubmitError] = useState("");
    const [cooldownUntil, setCooldownUntil] = useState(0);
    const [userLevel, setUserLevel] = useState(null);
    const [success, setSuccess] = useState(false);

    useEffect(() => {
        const fetchUserStatus = async () => {
            try {
                const data = await Api.get('get_user_status', { address: publicKey, _cb: Date.now() });
                if (data) {
                    setUserLevel(parseInt(data.user_level || 0));
                }
            } catch (e) {
                console.error('Failed to fetch user status:', e);
            }
        };

        if (publicKey) {
            fetchUserStatus();
        }
    }, [publicKey]);

    // Update elapsed time every 100ms when a status is active
    useEffect(() => {
        if (!statusStartTime || buttonStatus === "idle") {
            setElapsedTime(0);
            return;
        }
        const interval = setInterval(() => {
            setElapsedTime((Date.now() - statusStartTime) / 1000);
        }, 100);
        return () => clearInterval(interval);
    }, [statusStartTime, buttonStatus]);

    // Blur focused element when submitting to remove blinking cursor
    useEffect(() => {
        if (submitting && document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
    }, [submitting]);

    const checkUsernameAvailable = async (rawName) => {
        try {
            const base = String(rawName || "").trim();
            if (!base) return { available: false, error: "empty" };
            const data = await Api.get('get_address_from_username', { username: base });
            const available = !!(data && !data.exists);
            return { available, error: null };
        } catch (e) {
            return { available: false, error: String(e && e.message && e.message.includes('timeout') ? 'timeout' : 'network') };
        }
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        if (Date.now() < cooldownUntil) return;
        if (!publicKey) return;

        const inputPart = (usernameInput || "").trim();
        if (!inputPart) {
            setSubmitError("Username cannot be empty");
            return;
        }

        const isFreeUser = userLevel !== null && userLevel < 1;
        const newUsername = isFreeUser ? ("Anon-" + inputPart) : inputPart;

        // Use defaults if params not cached yet
        const minSize = getMinUsernameSize() ?? 5;
        const maxSize = getMaxUsernameSize() ?? 30;
        if (newUsername.length < minSize) {
            setSubmitError(`Username too short. Minimum ${minSize} characters required.`);
            return;
        }
        if (newUsername.length > maxSize) {
            setSubmitError(`Username too long. Maximum ${maxSize} characters allowed.`);
            return;
        }

        if (userLevel === null) {
            setSubmitError("Loading account information...");
            return;
        }

        if (newUsername === currentUsername) {
            setSubmitError("New username is the same as current username");
            return;
        }

        setSubmitError("");
        setSubmitting(true);
        setButtonStatus("checking");
        setStatusStartTime(Date.now());
        // Allow React to render the status update before starting the async operation
        await new Promise(r => setTimeout(r, 50));

        const availRes = await checkUsernameAvailable(newUsername);
        if (!availRes || availRes.error) {
            setSubmitError("Cannot check username: server unavailable");
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            setSubmitting(false);
            setButtonStatus("idle");
            setStatusStartTime(null);
            return;
        }
        if (!availRes.available) {
            setSubmitError("Username already taken");
            const until = Date.now() + 1000;
            setCooldownUntil(until);
            setTimeout(() => setCooldownUntil(0), 1000);
            setSubmitting(false);
            setButtonStatus("idle");
            setStatusStartTime(null);
            return;
        }

        // Stage 1: Preparing (PoW + transaction creation)
        setButtonStatus("preparing");
        setStatusStartTime(Date.now());
        await new Promise(r => setTimeout(r, 50)); // Let React render
        try {
            const result = await tx.setUsername(newUsername);

            if (!result || !result.success) {
                const msg = String((result && result.error) || "Submit failed");
                if (/admin insufficient balance/i.test(msg)) {
                    setSubmitError("Your account balance is too low to cover the transaction fee.");
                } else if (/insufficient funds/i.test(msg)) {
                    setSubmitError("Insufficient funds to complete this transaction.");
                } else {
                    setSubmitError(msg);
                }
                const until = Date.now() + 1000;
                setCooldownUntil(until);
                setTimeout(() => setCooldownUntil(0), 1000);
                setSubmitting(false);
                setButtonStatus("idle");
                setStatusStartTime(null);
                return;
            }

            try {
                const txHash = (result && result.tx_hash) ? String(result.tx_hash).toLowerCase() : "";
                if (!txHash) throw new Error("missing tx hash");

                // Stage 2: Submitting (show for 1-2 seconds)
                setButtonStatus("submitting");
                setStatusStartTime(Date.now());
                await new Promise(r => setTimeout(r, 50)); // Let React render
                const submittingDuration = 1000 + Math.random() * 1000; // 1.0 to 2.0 seconds
                await new Promise(r => setTimeout(r, submittingDuration));

                // Stage 3: Verifying (4s initial, then 2s intervals, max 5 attempts)
                setButtonStatus("verifying");
                setStatusStartTime(Date.now());
                await new Promise(r => setTimeout(r, 50)); // Let React render
                const pollResult = await tx.pollTxStatus(txHash);
                if (!pollResult) throw new Error('confirmation timeout');
                if (!pollResult.success) {
                    throw new Error(pollResult.error_details?.message || 'transaction rejected');
                }

                Storage.save('username', newUsername);
                setSuccess(true);
                setButtonStatus("idle");
                setStatusStartTime(null);
                setTimeout(() => {
                    navigate('/profile');
                    window.location.reload();
                }, 3000);
            } catch (e) {
                setSubmitError(String(e && e.message ? e.message : 'Failed to confirm transaction'));
                setSubmitting(false);
                setButtonStatus("idle");
                setStatusStartTime(null);
                return;
            }
        } catch (e) {
            setSubmitError(String(e?.message || e || "Submit failed"));
            setSubmitting(false);
            setButtonStatus("idle");
            setStatusStartTime(null);
        }
    };

    const canChangeName = userLevel !== null && userLevel >= 1;

    return (
        <>
            <Helmet>
                <title>Change Username | Mirage</title>
            </Helmet>
            {submitting && <BlockingOverlay />}
            <ContentGrid>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <ContainerTab>Change Username</ContainerTab>
                            <ContainerBody>
                                <Centered>
                                    {!success && (
                                        <>
                                            {!canChangeName && userLevel !== null && (
                                                <WarningBox>
                                                    Free tier accounts will always have the "Anon-" prefix. <Link to="/subscription">Upgrade to remove the "Anon-" prefix</Link>.
                                                </WarningBox>
                                            )}


                                            <InputWrapper $disabled={submitting}>
                                                {!canChangeName && <InputPrefix>Anon-</InputPrefix>}
                                                <StyledInputBox
                                                    placeholder={!canChangeName && currentUsername.startsWith('Anon-') ? currentUsername.slice(5) : (currentUsername || 'New username')}
                                                    value={usernameInput}
                                                    $hasPrefix={!canChangeName}
                                                    onChange={(e) => {
                                                        const raw = e.target.value;
                                                        const cleaned = raw.replace(/[^A-Za-z0-9-]/g, "");
                                                        const maxLen = getMaxInputLength(!canChangeName);
                                                        // If params not loaded yet, allow up to 100 chars temporarily
                                                        setUsernameInput(cleaned.slice(0, maxLen ?? 100));
                                                        setSubmitError("");
                                                    }}
                                                    onKeyDown={async (e) => {
                                                        if (e.key === 'Enter') {
                                                            e.preventDefault();
                                                            await handleSubmit(e);
                                                        }
                                                    }}
                                                    onPaste={(e) => {
                                                        // Block paste to prevent accidental seed phrase entry
                                                        e.preventDefault();
                                                    }}
                                                    maxLength={getMaxInputLength(!canChangeName) || 100}
                                                    disabled={submitting}
                                                />
                                            </InputWrapper>

                                            <ButtonWrapper>
                                                <Button
                                                    onClick={handleSubmit}
                                                    disabled={submitting || (Date.now() < cooldownUntil) || (usernameInput.trim() === '')}
                                                    fullWidth
                                                    loading={submitting}
                                                >
                                                    {buttonStatus === "checking" ? 'Checking...' :
                                                        buttonStatus === "preparing" ? 'Preparing...' :
                                                            buttonStatus === "submitting" ? 'Submitting...' :
                                                                buttonStatus === "verifying" ? 'Verifying...' :
                                                                    'Change Username'}
                                                </Button>
                                            </ButtonWrapper>

                                            {submitError && (
                                                <div style={{ color: '#f66', marginTop: '0.75rem', fontSize: '0.8rem' }}>{submitError}</div>
                                            )}
                                        </>
                                    )}

                                    {success && (
                                        <SuccessBox>
                                            <SuccessTitle>Username Changed!</SuccessTitle>
                                            <SuccessText>Your new username is:</SuccessText>
                                            <SuccessText><strong>{canChangeName ? usernameInput : ('Anon-' + usernameInput)}</strong></SuccessText>
                                            <SuccessSubtext>Redirecting to profile...</SuccessSubtext>
                                        </SuccessBox>
                                    )}
                                </Centered>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        </>
    );
}

export default ChangeUsernameView;
