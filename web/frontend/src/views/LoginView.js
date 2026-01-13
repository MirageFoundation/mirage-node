import React, { useState, useRef, useEffect } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import Button from "../components/Button";
import { useNavigate, useLocation } from 'react-router-dom';
import { deriveKeysFromSeed } from '../utils/CryptoUtils.js';
import { validateMnemonic } from 'bip39';
import Api from '../lib/api';
import Storage from '../utils/Storage';
import AuthPageShell from "../components/AuthPageShell";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed } from "../styled/Layout";

const Centered = styled.div`
    text-align: center;
    max-width: 800px;
    margin: 0 auto;
    padding: 0 0.5rem;
`;

const StyledTextArea = styled.textarea`    
    border: 1px solid ${({ theme }) => theme?.colors?.text || 'white'};
    display: block;
    width: 100%;
    max-width: 400px;
    min-height: 120px;
    margin: 8px auto;    
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCC'};
    text-align: left;
    resize: vertical;
    font-size: 0.75rem;
    line-height: 1.5;
    padding: 0.75rem 1rem;
    box-sizing: border-box;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;

    &:hover,&:focus {
        background-color: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
    }
`;

const ButtonWrapper = styled.div`
    display: flex;
    justify-content: center;
    margin: 12px auto;
    max-width: 400px;
`;


const IntroP = styled.p`
    margin: 0.35rem 0;
    line-height: 1.35;
    font-size: 0.75rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCC'};
    max-width: 800px;
    margin-bottom: 0.7rem;
`;

const ErrorMessage = styled.div`
    color: #f66;
    margin-top: 0.5rem;
    font-size: 0.8rem;
    max-width: 400px;
    margin-left: auto;
    margin-right: auto;
`;

function LoginView({ state, setCredentials }) {
    const navigate = useNavigate();
    const location = useLocation();
    const mountedRef = useRef(true);

    const [seedPhrase, setSeedPhrase] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    // If user is already signed in, redirect to their profile
    useEffect(() => {
        if (state.publicKey) {
            navigate('/profile', { replace: true });
        }
    }, [state.publicKey, navigate]);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    const fetchUsernameFromAddress = async (address) => {
        try {
            const data = await Api.get('get_username_from_address', { address }, { timeoutMs: 10000 });
            return data?.username || null;
        } catch (e) {
            return null;
        }
    };


    const handleLoginWithSeed = async () => {
        setError('');
        setLoading(true);

        try {
            const trimmedSeed = seedPhrase.trim();

            if (!trimmedSeed) {
                if (mountedRef.current) setError('Please enter your recovery phrase');
                if (mountedRef.current) setLoading(false);
                return;
            }

            if (!validateMnemonic(trimmedSeed)) {
                if (mountedRef.current) setError('Invalid recovery phrase');
                if (mountedRef.current) setLoading(false);
                return;
            }

            const { publicKey } = deriveKeysFromSeed(trimmedSeed);

            const username = await fetchUsernameFromAddress(publicKey);

            if (!username) {
                // Account not found - redirect to create account with the provided seed
                if (mountedRef.current) setLoading(false);
                navigate('/create_account', { 
                    state: { 
                        importedSeed: trimmedSeed,
                        fromRecovery: true 
                    },
                    replace: true 
                });
                return;
            }

            // Dismiss the welcome card for returning users (they already know the app)
            try { Storage.save('welcome_card_dismissed_v1', true); } catch (_) { }

            setCredentials(publicKey, username, trimmedSeed);
            navigate('/');
        } catch (e) {
            if (mountedRef.current) setError(String(e?.message || e || 'Login failed'));
        } finally {
            if (mountedRef.current) setLoading(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        await handleLoginWithSeed();
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Sign In | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <AuthPageShell activeTab="login">
                        <Centered>
                            <IntroP>
                                Sign in to your existing Mirage account with your 12-word recovery phrase<br />(each word is separated by a space):
                            </IntroP>

                            <form onSubmit={handleSubmit}>
                                <StyledTextArea
                                    placeholder="Enter your 12-word recovery phrase here"
                                    value={seedPhrase}
                                    onChange={(e) => {
                                        setSeedPhrase(e.target.value);
                                        setError('');
                                    }}
                                    disabled={loading}
                                />
                                <IntroP style={{ marginTop: '0.5rem', fontSize: '0.7rem' }}>
                                    Your username will be automatically retrieved from the blockchain.
                                </IntroP>

                                {error && <ErrorMessage>{error}</ErrorMessage>}

                                <ButtonWrapper>
                                    <Button type="submit" disabled={loading} fullWidth loading={loading}>
                                        {loading ? 'Signing in...' : 'Sign In'}
                                    </Button>
                                </ButtonWrapper>
                            </form>

                            <div style={{ marginTop: '1rem', fontSize: '0.6rem', color: '#999' }}>
                                Don't have an account?{' '}
                                <span
                                    style={{ color: '#4a9eff', cursor: 'pointer', fontSize: '0.6rem' }}
                                    onMouseEnter={(e) => e.target.style.textDecoration = 'underline'}
                                    onMouseLeave={(e) => e.target.style.textDecoration = 'none'}
                                    onClick={() => navigate('/create_account')}
                                >
                                    Create one here
                                </span>.<br /><br />

                            </div>
                        </Centered>
                    </AuthPageShell>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

export default LoginView;

