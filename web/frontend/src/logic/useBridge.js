import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useTheme } from "styled-components";
import { useLocation, useSearchParams } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import { bridgeBurn, pollTxStatus } from "../utils/tx";
import transactionHandler from "../utils/TransactionHandler";
import { formatError } from "../utils/errorMessages";

// Lazy import for Solana bridge - only loads when needed
export const loadSolanaBridge = () => import('../utils/solanaBridge');

// Network configurations - static metadata for supported bridge destinations
export const NETWORKS = {
    solana: {
        id: 'solana',
        name: 'Solana',
        symbol: 'SOL',
        icon: '/images/bridges/solana.svg',
        color: '#14F195',
        colorLight: 'rgba(20, 241, 149, 0.15)',
        addressPrefix: null,
        // Solana uses base58, not bech32
        addressLength: 44,
        estimatedTime: '~2-5 minutes',
        minAmount: 10,
        enabled: true,
        canDerive: false // Different cryptography, no derived address
    }
};

// Polling schedule: 1s for first 30s, then 2s for 30-60s, then 3s after
export const BRIDGE_POLL_SCHEDULE = {
    initialDelayMs: 1000,
    intervalsMs: [...Array.from({
        length: 30
    }, () => 1000),
    // 0-30s: every 1s
    ...Array.from({
        length: 15
    }, () => 2000),
    // 30-60s: every 2s
    ...Array.from({
        length: 20
    }, () => 3000) // 60-120s: every 3s
    ]
};

// Bridge status polling schedule for Bridge Out (Mirage -> external)
// First poll at 10s, then every 2.5s until 60s, then every 5s. Timeout at 120s.
export const BRIDGE_OUT_STATUS_POLL_SCHEDULE = {
    initialDelayMs: 10000,
    // Wait 10s before first poll (validators need time to detect burn and attest)
    intervalsMs: [...Array.from({
        length: 20
    }, () => 2500),
    // 10-60s: every 2.5s (20 * 2.5s = 50s)
    ...Array.from({
        length: 12
    }, () => 5000) // 60-120s: every 5s (12 * 5s = 60s)
    ]
};
export const formatAttestationPower = (attestedPower, requiredPower, thresholdBps) => {
    const required = Number(requiredPower) || 0;
    const threshold = Number(thresholdBps) || 0;
    if (required <= 0 || threshold <= 0) return '';
    const thresholdPercent = threshold / 100;
    const percentOfTotal = Math.min(100, (Number(attestedPower) || 0) / required * thresholdPercent);
    return `${percentOfTotal.toFixed(1)}% power, need ${thresholdPercent.toFixed(1)}%`;
};

// Truncate long addresses for mobile display
export const truncateAddress = (addr, startChars = 10, endChars = 6) => {
    if (!addr) return '';
    if (addr.length <= startChars + endChars + 3) return addr;
    return `${addr.slice(0, startChars)}...${addr.slice(-endChars)}`;
};

// Responsive address component - shows truncated on mobile, full on desktop

// Source network configurations for Bridge In (where tokens come FROM)
export const SOURCE_NETWORKS = {
    solana: {
        id: 'solana',
        name: 'Solana',
        symbol: 'SOL',
        icon: '/images/bridges/solana.svg',
        color: '#14F195',
        colorLight: 'rgba(20, 241, 149, 0.15)',
        estimatedTime: '~2-5 minutes',
        enabled: true
    }
};

// Solana wallet button

// Solana RPC endpoints
export const SOLANA_RPC_DEVNET = 'https://api.devnet.solana.com';
export const SOLANA_RPC_MAINNET = 'https://api.mainnet-beta.solana.com';

// Bridge status polling schedule for Bridge In (Solana -> Mirage)
// First poll at 10s, then every 2.5s until 60s, then every 5s. Timeout at 120s.
export const BRIDGE_IN_STATUS_POLL_SCHEDULE = {
    initialDelayMs: 10000,
    // Wait 10s before first poll (orchestrators need time to detect burn and attest)
    intervalsMs: [...Array.from({
        length: 20
    }, () => 2500),
    // 10-60s: every 2.5s (20 * 2.5s = 50s)
    ...Array.from({
        length: 12
    }, () => 5000) // 60-120s: every 5s (12 * 5s = 60s)
    ]
};

// Solana Bridge In Flow Component
export function useSolanaBridgeInFlow({
    mirageAddress,
    theme,
    chainConfigs,
    attestationThresholdBps,
    onBridgingChange
}) {
    const [solanaWallet, setSolanaWallet] = useState(null); // { address, mirageBalance, solBalance }
    const [isConnecting, setIsConnecting] = useState(false);
    const [amount, setAmount] = useState('');
    const [isBridging, setIsBridging] = useState(false);
    const [bridgeStatus, setBridgeStatus] = useState('idle'); // idle | confirming | pending | complete | error
    const [bridgeError, setBridgeError] = useState('');
    const [bridgeTxHash, setBridgeTxHash] = useState('');
    const [burnNonce, setBurnNonce] = useState(null);

    // Step tracking for progress UI
    const [stepTimestamps, setStepTimestamps] = useState({});
    const [stepElapsed, setStepElapsed] = useState({});
    const [mintStatus, setMintStatus] = useState({
        state: 'idle',
        txHash: '',
        error: ''
    });
    const [attestationProgress, setAttestationProgress] = useState({
        attestorCount: 0,
        attestedPower: 0,
        requiredPower: 0,
        confirmed: false
    });
    const buttonRef = useRef(null);

    // Pre-bridge balance tracking for progress screen
    const [preBridgeSolanaBalance, setPreBridgeSolanaBalance] = useState(null);
    const [bridgeAmount, setBridgeAmount] = useState(''); // Store amount at bridge time

    // Track Mirage chain balance separately from Solana wallet balances
    const [, setMirageChainBalance] = useState(null);
    const refreshMirageBalance = useCallback(async (reason = 'init') => {
        if (!mirageAddress) {
            setMirageChainBalance(null);
            console.debug('[Solana Bridge] Mirage balance fetch skipped (no address)');
            return;
        }
        console.debug('[Solana Bridge] Fetching Mirage balance', {
            address: mirageAddress,
            reason
        });
        try {
            const data = await Api.get('get_user_status', {
                address: mirageAddress,
                _cb: Date.now()
            }, {
                headers: {
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            });
            const balanceVal = Number(data?.balance);
            if (!Number.isFinite(balanceVal)) {
                throw new Error('Invalid balance from get_user_status');
            }
            setMirageChainBalance(balanceVal);
            console.debug('[Solana Bridge] Mirage balance updated', {
                balance: balanceVal
            });
        } catch (e) {
            console.error('[Solana Bridge] Mirage balance fetch failed:', e);
        }
    }, [mirageAddress]);
    useEffect(() => {
        refreshMirageBalance('init');
    }, [refreshMirageBalance]);
    useEffect(() => {
        if (bridgeStatus !== 'complete') return;
        refreshMirageBalance('minted');
    }, [bridgeStatus, refreshMirageBalance]);

    // Scroll to button when bridge status changes from idle
    useEffect(() => {
        if (bridgeStatus === 'idle') return;
        if (!buttonRef.current) return;
        try {
            buttonRef.current.scrollIntoView({
                behavior: 'smooth',
                block: 'end'
            });
        } catch (_) { }
    }, [bridgeStatus]);

    // Notify parent when bridging status changes
    useEffect(() => {
        if (onBridgingChange) {
            onBridgingChange(bridgeStatus !== 'idle');
        }
    }, [bridgeStatus, onBridgingChange]);

    // Get Solana config from chainConfigs
    const solanaConfig = chainConfigs?.solana || {};
    const solanaCluster = solanaConfig.solana_cluster || 'devnet';
    const solanaTokenAddress = solanaConfig.solana_token_address || '';
    const solanaRpcUrl = solanaCluster === 'mainnet' ? SOLANA_RPC_MAINNET : SOLANA_RPC_DEVNET;
    const solscanClusterParam = solanaCluster === 'devnet' ? '?cluster=devnet' : '';

    // Update elapsed times every 100ms while actively processing
    useEffect(() => {
        if (bridgeStatus === 'idle' || bridgeStatus === 'error' || bridgeStatus === 'complete') return;
        const stepOrder = ['confirming', 'pending', 'complete'];
        const currentStepIdx = stepOrder.indexOf(bridgeStatus);
        const interval = setInterval(() => {
            const now = Date.now();
            setStepElapsed(prev => {
                const newElapsed = {
                    ...prev
                };
                for (const [step, startTime] of Object.entries(stepTimestamps)) {
                    const stepIdx = stepOrder.indexOf(step);
                    // Only update elapsed time for current or future steps
                    // For completed steps, freeze at when next step started
                    if (stepIdx < currentStepIdx) {
                        const nextStep = stepOrder[stepIdx + 1];
                        const nextStepStart = stepTimestamps[nextStep];
                        if (nextStepStart) {
                            newElapsed[step] = (nextStepStart - startTime) / 1000;
                        }
                    } else {
                        newElapsed[step] = (now - startTime) / 1000;
                    }
                }
                return newElapsed;
            });
        }, 100);
        return () => clearInterval(interval);
    }, [bridgeStatus, stepTimestamps]);

    // Poll for mint confirmation on Mirage after Solana burn is confirmed
    useEffect(() => {
        if (bridgeStatus !== 'pending' || burnNonce === null) return;
        let cancelled = false;
        const maxAttempts = BRIDGE_IN_STATUS_POLL_SCHEDULE.intervalsMs.length + 1;
        const initialDelayMs = BRIDGE_IN_STATUS_POLL_SCHEDULE.initialDelayMs;
        let attestationFoundTime = null; // Track when we first see found=true

        setMintStatus({
            state: 'pending',
            txHash: '',
            error: ''
        });
        setAttestationProgress({
            attestorCount: 0,
            attestedPower: 0,
            requiredPower: 0,
            confirmed: false
        });
        const poll = async attempt => {
            if (cancelled) return;
            try {
                console.debug('[Solana Bridge In] Status poll attempt', attempt, 'of', maxAttempts, 'burn_sequence:', burnNonce);

                // Query bridge status (includes attestor count)
                const res = await fetch(`/api/bridge/status?burn_sequence=${burnNonce}&chain=solana`);
                if (!res.ok) {
                    throw new Error(`status query failed (${res.status})`);
                }
                const data = await res.json();
                console.debug('[Solana Bridge In] Bridge status response:', data);

                // Track when attestation is first found (orchestrator detected the burn)
                if (data.found && !attestationFoundTime) {
                    attestationFoundTime = Date.now();
                    // Freeze the "Validator attestations" step timer
                    setStepElapsed(prev => {
                        const pendingStart = stepTimestamps.pending;
                        if (pendingStart) {
                            return {
                                ...prev,
                                pending: (attestationFoundTime - pendingStart) / 1000
                            };
                        }
                        return prev;
                    });
                    console.debug('[Solana Bridge In] Attestation found, starting mint timer');
                }

                // Update attestation progress from status response
                if (data.found) {
                    setAttestationProgress(prev => ({
                        ...prev,
                        attestorCount: data.attestor_count || prev.attestorCount,
                        attestedPower: data.attested_power ?? prev.attestedPower,
                        requiredPower: data.required_power ?? prev.requiredPower,
                        confirmed: data.confirmed || prev.confirmed
                    }));
                }
                if (data.confirmed) {
                    setMintStatus({
                        state: 'minted',
                        txHash: data.mint_tx || '',
                        error: ''
                    });
                    // Calculate final elapsed time for the 'complete' (mint) step
                    const now = Date.now();
                    const mintStartTime = attestationFoundTime || stepTimestamps.pending || now;
                    setStepTimestamps(prev => ({
                        ...prev,
                        complete: now
                    }));
                    setStepElapsed(prev => ({
                        ...prev,
                        complete: (now - mintStartTime) / 1000
                    }));
                    setBridgeStatus('complete');
                    return;
                }
            } catch (e) {
                console.debug('[Solana Bridge In] Status poll error:', e.message);
            }
            if (attempt >= maxAttempts) {
                setMintStatus({
                    state: 'timeout',
                    txHash: '',
                    error: 'Confirmation taking longer than expected'
                });
                return;
            }
            const nextDelay = BRIDGE_IN_STATUS_POLL_SCHEDULE.intervalsMs[attempt - 1] || 60000;
            console.debug('[Solana Bridge In] Status poll next delay (ms):', nextDelay);
            setTimeout(() => poll(attempt + 1), nextDelay);
        };
        if (initialDelayMs > 0) {
            setTimeout(() => poll(1), initialDelayMs);
        } else {
            poll(1);
        }
        return () => {
            cancelled = true;
        };
    }, [bridgeStatus, burnNonce, stepTimestamps.pending]);

    // Format step time for display
    const formatStepTime = step => {
        const elapsed = stepElapsed[step];
        if (elapsed === undefined) return '';
        return ` (${elapsed.toFixed(1)}s)`;
    };
    const attestationPowerText = formatAttestationPower(attestationProgress.attestedPower, attestationProgress.requiredPower, attestationThresholdBps);

    // Get step state for styling
    const getStepState = step => {
        if (bridgeStatus === 'idle') return 'pending';
        const stepOrder = ['confirming', 'pending', 'complete'];
        const currentIdx = stepOrder.indexOf(bridgeStatus);
        const stepIdx = stepOrder.indexOf(step);
        if (bridgeStatus === 'error') {
            // Find which step had the error
            if (stepIdx < currentIdx) return 'complete';
            if (stepIdx === currentIdx) return 'error';
            return 'pending';
        }

        // When bridgeStatus is 'complete', all steps are complete
        if (bridgeStatus === 'complete') return 'complete';
        if (stepIdx < currentIdx) return 'complete';
        if (stepIdx === currentIdx) return 'active';
        return 'pending';
    };

    // Format number with thousands separators for display
    const formatAmountDisplay = value => {
        if (!value || value === '') return '';
        const raw = String(value).replace(/,/g, '');
        const parts = raw.split('.');
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return parts.join('.');
    };

    // Fetch MIRAGE token balance from Solana
    const fetchSolanaBalance = useCallback(async walletAddress => {
        try {
            // Fetch SOL balance and MIRAGE token balance in parallel
            const [solResponse, tokenResponse] = await Promise.all([
                // SOL balance
                fetch(solanaRpcUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id: 1,
                        method: 'getBalance',
                        params: [walletAddress]
                    })
                }),
                // MIRAGE token balance
                solanaTokenAddress ? fetch(solanaRpcUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id: 2,
                        method: 'getTokenAccountsByOwner',
                        params: [walletAddress, {
                            mint: solanaTokenAddress
                        }, {
                                encoding: 'jsonParsed'
                            }]
                    })
                }) : Promise.resolve(null)]);

            // Parse SOL balance
            const solData = await solResponse.json();
            const solBalance = (solData.result?.value || 0) / 1_000_000_000; // lamports to SOL
            console.debug('[Solana Bridge] SOL balance:', solBalance);

            // Parse MIRAGE balance
            let mirageBalance = 0;
            if (tokenResponse) {
                const tokenData = await tokenResponse.json();
                console.debug('[Solana Bridge] MIRAGE token accounts:', tokenData);
                if (tokenData.result?.value?.length > 0) {
                    for (const account of tokenData.result.value) {
                        const info = account.account?.data?.parsed?.info;
                        if (info) {
                            const amount = info.tokenAmount?.uiAmount || 0;
                            console.debug('[Solana Bridge] Found MIRAGE:', info.mint, 'amount:', amount);
                            mirageBalance += amount;
                        }
                    }
                }
            } else {
                console.warn('[Solana Bridge] No token address configured');
            }
            setSolanaWallet(prev => prev ? {
                ...prev,
                mirageBalance,
                solBalance
            } : null);
        } catch (e) {
            console.error('[Solana Bridge] Balance fetch error:', e);
            setSolanaWallet(prev => prev ? {
                ...prev,
                mirageBalance: 0,
                solBalance: 0
            } : null);
        }
    }, [solanaRpcUrl, solanaTokenAddress]);

    // Connect to Phantom wallet
    const connectPhantom = async () => {
        setIsConnecting(true);
        setBridgeError('');
        try {
            // Check if Phantom is installed
            const {
                solana
            } = window;
            if (!solana?.isPhantom) {
                window.open('https://phantom.app/', '_blank');
                throw new Error('Phantom wallet not found. Please install it.');
            }

            // Connect
            const response = await solana.connect();
            const publicKey = response.publicKey.toString();
            setSolanaWallet({
                address: publicKey,
                mirageBalance: null,
                // Will be fetched
                solBalance: null // Will be fetched
            });
            console.debug('[Solana Bridge] Connected:', publicKey);

            // Fetch balance
            await fetchSolanaBalance(publicKey);
        } catch (e) {
            console.error('[Solana Bridge] Connection error:', e);
            setBridgeError(e.message || 'Failed to connect wallet');
        } finally {
            setIsConnecting(false);
        }
    };

    // Disconnect wallet
    const disconnectWallet = async () => {
        try {
            const {
                solana
            } = window;
            if (solana) {
                await solana.disconnect();
            }
        } catch (e) {
            console.error('[Solana Bridge] Disconnect error:', e);
        }
        setSolanaWallet(null);
        setAmount('');
        setBridgeStatus('idle');
        setBridgeError('');
        setBridgeTxHash('');
        setBurnNonce(null);
        setStepTimestamps({});
        setStepElapsed({});
        setMintStatus({
            state: 'idle',
            txHash: '',
            error: ''
        });
    };

    // Handle bridge (burn on Solana)
    const handleBridge = async () => {
        if (!solanaWallet || !amount || parseFloat(amount) <= 0) return;
        const programId = solanaConfig.solana_program_id;
        if (!programId) {
            setBridgeError('Bridge program not configured');
            return;
        }

        // Capture pre-bridge balances for the progress screen
        setPreBridgeSolanaBalance(solanaWallet.mirageBalance);
        setBridgeAmount(amount.replace(/,/g, ''));

        // Reset state
        setIsBridging(true);
        setBridgeStatus('confirming');
        setBridgeError('');
        setBridgeTxHash('');
        setBurnNonce(null);
        setMintStatus({
            state: 'idle',
            txHash: '',
            error: ''
        });
        setStepTimestamps({
            confirming: Date.now()
        });
        setStepElapsed({});
        try {
            // Convert amount to base units (6 decimals)
            const rawAmount = amount.replace(/,/g, '');
            const amountBaseUnits = Math.floor(parseFloat(rawAmount) * 1_000_000);
            if (amountBaseUnits <= 0) {
                throw new Error('Invalid amount');
            }
            console.debug('[Solana Bridge] Starting burn', {
                amount: rawAmount,
                amountBaseUnits,
                recipient: mirageAddress,
                programId
            });

            // Lazy-load Solana bridge module (only loaded when user actually bridges)
            const {
                executeBurn
            } = await loadSolanaBridge();

            // Execute the burn transaction
            const result = await executeBurn({
                rpcUrl: solanaRpcUrl,
                programIdStr: programId,
                mirageRecipient: mirageAddress,
                amount: amountBaseUnits,
                onStatus: status => {
                    console.debug('[Solana Bridge] Status:', status);
                }
            });
            console.debug('[Solana Bridge] Burn successful', result);
            console.debug('[Solana Bridge] Burn nonce for polling:', result.burnNonce);
            setBridgeTxHash(result.signature);
            setBurnNonce(result.burnNonce !== undefined ? Number(result.burnNonce) : null);
            setBridgeStatus('pending');
            setStepTimestamps(prev => ({
                ...prev,
                pending: Date.now()
            }));

            // Refresh balance after successful burn
            if (solanaWallet?.address) {
                fetchSolanaBalance(solanaWallet.address);
            }
        } catch (e) {
            console.error('[Solana Bridge] Bridge error:', e);
            setBridgeStatus('error');
            // Clean up error message
            let errorMsg = e.message || 'Bridge transaction failed';
            if (errorMsg.includes('User rejected')) {
                errorMsg = 'Transaction cancelled by user';
            } else if (errorMsg.includes('Insufficient')) {
                errorMsg = 'Insufficient MIRAGE balance';
            } else if (errorMsg.includes('paused')) {
                errorMsg = 'Bridge is currently paused';
            }
            setBridgeError(errorMsg);
        } finally {
            setIsBridging(false);
        }
    };

    // Amount validation
    const amountError = useMemo(() => {
        if (!amount) return null;
        const num = parseFloat(amount);
        if (isNaN(num) || num <= 0) return 'Enter a valid amount';
        if (solanaWallet?.mirageBalance !== null && num > solanaWallet.mirageBalance) {
            return 'Insufficient balance';
        }
        return null;
    }, [amount, solanaWallet?.mirageBalance]);
    const canBridge = solanaWallet && amount && parseFloat(amount) > 0 && !amountError && !isBridging && (bridgeStatus === 'idle' || bridgeStatus === 'error');

    // Reset for new bridge
    const handleNewBridge = () => {
        setAmount('');
        setBridgeStatus('idle');
        setBridgeError('');
        setBridgeTxHash('');
        setBurnNonce(null);
        setStepTimestamps({});
        setStepElapsed({});
        setMintStatus({
            state: 'idle',
            txHash: '',
            error: ''
        });
        setPreBridgeSolanaBalance(null);
        setBridgeAmount('');
        // Refresh balances
        refreshMirageBalance('new_bridge');
        if (solanaWallet?.address) {
            fetchSolanaBalance(solanaWallet.address);
        }
    };

    // Show progress screen when bridging is in progress
    const showProgressScreen = bridgeStatus !== 'idle';

    // If showing progress screen, render the progress view
    return {
        solanaWallet,
        isConnecting,
        amount,
        setAmount,
        isBridging,
        bridgeStatus,
        bridgeError,
        bridgeTxHash,
        mintStatus,
        attestationProgress,
        buttonRef,
        preBridgeSolanaBalance,
        bridgeAmount,
        solanaCluster,
        solscanClusterParam,
        formatStepTime,
        attestationPowerText,
        getStepState,
        formatAmountDisplay,
        connectPhantom,
        disconnectWallet,
        handleBridge,
        amountError,
        canBridge,
        handleNewBridge,
        showProgressScreen
    };
}
export function useBridgeInPanel({
    address,
    chainConfigs,
    attestationThresholdBps,
    balance,
    balanceLoading,
    balanceError,
    refreshBalance,
    formatBalance
}) {
    const theme = useTheme();
    const [selectedSource, setSelectedSource] = useState(null);
    const [isSolanaBridging, setIsSolanaBridging] = useState(false); // Track when Solana bridge is in progress

    const handleSourceSelect = networkId => {
        setSelectedSource(SOURCE_NETWORKS[networkId]);
        console.debug('[Bridge In] Selected source:', networkId);
    };
    const handleSolanaBridgingChange = useCallback(isBridging => {
        setIsSolanaBridging(isBridging);
    }, []);
    return {
        theme,
        selectedSource,
        isSolanaBridging,
        handleSourceSelect,
        handleSolanaBridgingChange
    };
}
export function useBridge({
    state
}) {
    const location = useLocation();
    const theme = useTheme();
    const [searchParams, setSearchParams] = useSearchParams();
    const address = Storage.load('publicKey', '') || '';
    const valoperAddress = (() => {
        try {
            const raw = localStorage.getItem('nodeConfig');
            if (raw) {
                const cfg = JSON.parse(raw);
                if (cfg.validator_operator_address) return cfg.validator_operator_address;
            }
        } catch (_) { }
        return '';
    })();

    // Get initial tab from URL, default to 'out'
    const tabFromUrl = searchParams.get('tab');
    const initialTab = tabFromUrl === 'in' || tabFromUrl === 'out' ? tabFromUrl : 'out';

    // State - restore selected network and address from localStorage
    const [activeTab, setActiveTab] = useState(initialTab);
    const [selectedNetwork, setSelectedNetwork] = useState(() => {
        const savedNetworkId = localStorage.getItem('bridge_out_network');
        return savedNetworkId && NETWORKS[savedNetworkId] ? NETWORKS[savedNetworkId] : null;
    });
    const [amount, setAmount] = useState('');
    const [destinationAddress, setDestinationAddress] = useState(() => {
        const savedNetworkId = localStorage.getItem('bridge_out_network');
        return savedNetworkId ? localStorage.getItem(`bridge_dest_${savedNetworkId}`) || '' : '';
    });
    const [useDifferentAddress, setUseDifferentAddress] = useState(false);
    const [balance, setBalance] = useState(null);
    const [balanceLoading, setBalanceLoading] = useState(false);
    const [balanceError, setBalanceError] = useState(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitStage, setSubmitStage] = useState('idle'); // idle | submitting | verifying | confirmed | error
    const [submitError, setSubmitError] = useState('');
    const [submitTxHash, setSubmitTxHash] = useState('');
    const [, setVerificationProgress] = useState({
        attempt: 0,
        maxAttempts: 0
    });
    const [errorStage, setErrorStage] = useState(null);
    const [errors, setErrors] = useState({});
    const stepsRef = useRef(null);

    // Step timing: track when each step started and current elapsed times
    const [stepTimestamps, setStepTimestamps] = useState({});
    const [stepElapsed, setStepElapsed] = useState({});
    const [mintStatus, setMintStatus] = useState({
        state: 'idle',
        // idle | pending | minted | timeout | error
        destinationTx: '',
        destinationChain: '',
        error: '',
        completedAt: null // timestamp when mint completed (for final timer display)
    });
    const [outboundAttestationProgress, setOutboundAttestationProgress] = useState({
        attestorCount: 0,
        attestedPower: 0,
        requiredPower: 0,
        confirmed: false
    });
    const [chainConfigs, setChainConfigs] = useState({}); // chain_id -> { fee_mirage, enabled, ... }
    const [attestationThresholdBps, setAttestationThresholdBps] = useState(null);

    // Pre-bridge balance tracking for progress screen (Bridge Out)
    const [preBridgeMirageBalance, setPreBridgeMirageBalance] = useState(null);
    const [bridgeOutAmount, setBridgeOutAmount] = useState('');
    const [bridgeOutNetwork, setBridgeOutNetwork] = useState(null);

    // Sync tab state with URL changes (browser back/forward)
    useEffect(() => {
        const tab = searchParams.get('tab');
        if (tab === 'in' || tab === 'out') {
            if (tab !== activeTab) {
                setActiveTab(tab);
            }
        }
    }, [searchParams, activeTab]);

    // Fetch bridge config (per-chain fees) from backend
    useEffect(() => {
        fetch('/api/bridge/config').then(res => res.json()).then(data => {
            if (data.chains) {
                const configs = {};
                for (const chain of data.chains) {
                    configs[chain.chain_id] = chain;
                }
                setChainConfigs(configs);
                console.debug('[Bridge] Loaded chain configs:', configs);
            }
            if (typeof data.attestation_threshold_bps !== 'undefined') {
                setAttestationThresholdBps(Number(data.attestation_threshold_bps));
            }
        }).catch(err => console.error('[Bridge] Failed to load config:', err));
    }, []);

    // Bridge fee per chain (from backend config)
    const bridgeFee = useMemo(() => {
        if (!selectedNetwork) return null;
        const config = chainConfigs[selectedNetwork.id];
        if (!config) return null; // Chain not configured
        return config.fee_mirage;
    }, [selectedNetwork, chainConfigs]);

    // Derive the user's address on the destination chain (for Cosmos chains)
    // Note: Currently unused as only Solana bridge remains (different key derivation)
    const derivedAddress = useMemo(() => {
        if (!address || !selectedNetwork?.canDerive || !selectedNetwork?.addressPrefix) {
            return null;
        }
        // Cosmos address derivation removed with IBC/Osmosis (v1.10.0)
        return null;
    }, [address, selectedNetwork]);

    // The effective destination address (derived or manual)
    const effectiveDestination = useMemo(() => {
        if (selectedNetwork?.canDerive && !useDifferentAddress) {
            return derivedAddress;
        }
        return destinationAddress;
    }, [selectedNetwork, useDifferentAddress, derivedAddress, destinationAddress]);
    const refreshBalance = useCallback(async (reason = 'init') => {
        if (!address) {
            setBalance(null);
            setBalanceError(null);
            console.debug('[Bridge] Balance fetch skipped (no address)');
            return;
        }
        console.debug('[Bridge] Fetching on-chain balance', {
            address,
            reason
        });
        setBalanceLoading(true);
        setBalanceError(null);
        try {
            const data = await Api.get('get_user_status', {
                address,
                _cb: Date.now()
            }, {
                headers: {
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            });
            const balanceVal = Number(data?.balance);
            if (!Number.isFinite(balanceVal)) {
                throw new Error('Invalid balance from get_user_status');
            }
            setBalance(balanceVal);
            // Also sync to TopBar/MobileHeader via cacheUserStatus → _persistUserBalance → balanceUpdated event
            try {
                transactionHandler.cacheUserStatus(data);
            } catch (_) { }
            setBalanceError(null);
            console.debug('[Bridge] Balance updated', {
                balance: balanceVal
            });
        } catch (e) {
            console.error('[Bridge] Balance fetch failed:', e);
            setBalanceError(e.message || 'Failed to load balance');
        } finally {
            setBalanceLoading(false);
        }
    }, [address]);
    useEffect(() => {
        refreshBalance('init');
    }, [refreshBalance]);
    useEffect(() => {
        if (submitStage !== 'confirmed') return;
        refreshBalance('confirmed');
    }, [submitStage, refreshBalance]);

    // Validation
    const validateAmount = useCallback(value => {
        if (!value || value === '') return null;
        // Only show "Chain not configured" if config has loaded but chain isn't there
        const configLoaded = Object.keys(chainConfigs).length > 0;
        if (bridgeFee === null && configLoaded) return 'Chain not configured';
        if (bridgeFee === null) return null; // Still loading config
        const num = parseFloat(value);
        if (isNaN(num) || num <= 0) return 'Please enter a valid amount';
        // Fee is subtracted from amount, so amount must be greater than fee
        if (num <= bridgeFee) {
            return `Amount must be greater than ${bridgeFee} MIRAGE fee`;
        }
        const receiveAmt = num - bridgeFee;
        if (selectedNetwork && receiveAmt < selectedNetwork.minAmount) {
            return `Receive amount must be at least ${selectedNetwork.minAmount} MIRAGE (after ${bridgeFee} fee)`;
        }
        if (Number.isFinite(balance) && num > balance / 1_000_000) {
            return 'Insufficient balance';
        }
        return null;
    }, [selectedNetwork, balance, bridgeFee, chainConfigs]);
    const validateAddress = useCallback((value, isManualEntry = true) => {
        // If using derived address for Cosmos chains, no validation needed
        if (selectedNetwork?.canDerive && !isManualEntry) {
            return null;
        }
        if (!value || value === '') return null;
        if (!selectedNetwork) return null;
        const trimmed = value.trim();
        if (selectedNetwork.id === 'solana') {
            // Basic Solana address validation (base58, 32-44 chars)
            if (trimmed.length < 32 || trimmed.length > 44) {
                return 'Invalid Solana address length';
            }
            // Check for valid base58 characters
            if (!/^[1-9A-HJ-NP-Za-km-z]+$/.test(trimmed)) {
                return 'Invalid Solana address format';
            }
        }
        return null;
    }, [selectedNetwork]);
    useEffect(() => {
        if (submitStage === 'idle') return;
        if (!stepsRef.current) return;
        try {
            stepsRef.current.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        } catch (_) { }
    }, [submitStage]);

    // Handlers
    const resetSubmitState = useCallback(() => {
        setSubmitStage('idle');
        setSubmitError('');
        setSubmitTxHash('');
        setVerificationProgress({
            attempt: 0,
            maxAttempts: 0
        });
        setErrorStage(null);
        setStepTimestamps({});
        setStepElapsed({});
        setMintStatus({
            state: 'idle',
            destinationTx: '',
            destinationChain: '',
            error: '',
            completedAt: null
        });
        setOutboundAttestationProgress({
            attestorCount: 0,
            attestedPower: 0,
            requiredPower: 0,
            confirmed: false
        });
        setPreBridgeMirageBalance(null);
        setBridgeOutAmount('');
        setBridgeOutNetwork(null);
    }, []);

    // Track step timing: record timestamp when stage changes
    useEffect(() => {
        if (submitStage === 'idle') return;

        // Record timestamp for this step if not already set
        setStepTimestamps(prev => {
            if (prev[submitStage]) return prev;
            return {
                ...prev,
                [submitStage]: Date.now()
            };
        });
    }, [submitStage]);

    // Update elapsed times every 100ms while actively processing (not idle or error)
    useEffect(() => {
        if (submitStage === 'idle' || submitStage === 'error') return;
        const interval = setInterval(() => {
            const now = Date.now();
            setStepElapsed(prev => {
                const newElapsed = {
                    ...prev
                };
                for (const [step, startTime] of Object.entries(stepTimestamps)) {
                    newElapsed[step] = (now - startTime) / 1000;
                }
                return newElapsed;
            });
        }, 100);
        return () => clearInterval(interval);
    }, [submitStage, stepTimestamps]);
    useEffect(() => {
        if (submitStage !== 'confirmed') return;
        if (selectedNetwork?.id !== 'solana') return;
        if (!submitTxHash) return;
        let cancelled = false;
        const maxAttempts = BRIDGE_OUT_STATUS_POLL_SCHEDULE.intervalsMs.length + 1;
        const initialDelayMs = BRIDGE_OUT_STATUS_POLL_SCHEDULE.initialDelayMs;
        setMintStatus({
            state: 'pending',
            destinationTx: '',
            destinationChain: '',
            error: ''
        });
        setOutboundAttestationProgress({
            attestorCount: 0,
            attestedPower: 0,
            requiredPower: 0,
            confirmed: false
        });
        console.debug('[Bridge] Status poll schedule (ms):', {
            initialDelayMs,
            intervalsMs: BRIDGE_OUT_STATUS_POLL_SCHEDULE.intervalsMs
        });
        const poll = async (attempt = 1) => {
            if (cancelled) return;
            try {
                console.debug('[Bridge] Status poll attempt', attempt, 'of', maxAttempts);

                // Query bridge status (includes attestor count)
                const res = await fetch(`/api/bridge/status?burn_tx_hash=${submitTxHash}`);
                if (res.ok) {
                    const data = await res.json();
                    console.debug('[Bridge] Bridge status response:', data);

                    // Update attestation progress from status response
                    if (data.found) {
                        setOutboundAttestationProgress(prev => ({
                            ...prev,
                            attestorCount: data.attestor_count || prev.attestorCount,
                            attestedPower: data.attested_power ?? prev.attestedPower,
                            requiredPower: data.required_power ?? prev.requiredPower,
                            confirmed: data.confirmed || prev.confirmed
                        }));
                    }
                    if (data?.confirmed) {
                        setMintStatus({
                            state: 'minted',
                            destinationTx: data.destination_tx || '',
                            destinationChain: data.destination_chain || 'solana',
                            error: '',
                            completedAt: Date.now()
                        });
                        return;
                    }
                } else {
                    console.debug(`[Bridge] Status query error (${res.status}), retrying...`);
                }
            } catch (e) {
                console.debug('[Bridge] Status poll error:', e.message);
            }
            if (attempt >= maxAttempts) {
                setMintStatus({
                    state: 'timeout',
                    destinationTx: '',
                    destinationChain: '',
                    error: 'mint confirmation timed out',
                    completedAt: Date.now()
                });
                return;
            }
            const nextDelay = BRIDGE_OUT_STATUS_POLL_SCHEDULE.intervalsMs[attempt - 1];
            if (!nextDelay) {
                setMintStatus({
                    state: 'timeout',
                    destinationTx: '',
                    destinationChain: '',
                    error: 'mint confirmation timed out',
                    completedAt: Date.now()
                });
                return;
            }
            console.debug('[Bridge] Status poll next delay (ms):', nextDelay);
            setTimeout(() => poll(attempt + 1), nextDelay);
        };
        if (initialDelayMs > 0) {
            setTimeout(() => poll(1), initialDelayMs);
        } else {
            poll(1);
        }
        return () => {
            cancelled = true;
        };
    }, [submitStage, selectedNetwork?.id, submitTxHash]);
    const handleNewBridge = () => {
        setAmount('');
        // Keep destination address - it's saved in localStorage
        setUseDifferentAddress(false);
        resetSubmitState();
        setErrors(prev => ({
            ...prev,
            submit: null
        }));
        // Refresh balance
        refreshBalance('new_bridge');
        console.debug('[Bridge] Reset for new transaction');
    };
    const handleTabChange = tab => {
        setActiveTab(tab);
        setSearchParams({
            tab
        }); // Update URL
        resetSubmitState();
        setErrors(prev => ({
            ...prev,
            submit: null
        }));
        // Always refresh balance when switching tabs
        refreshBalance('tab_switch');
        console.debug('[Bridge] Tab changed:', tab);
    };
    const handleNetworkSelect = networkId => {
        setSelectedNetwork(NETWORKS[networkId]);
        // Save network selection and load saved address from localStorage
        localStorage.setItem('bridge_out_network', networkId);
        const savedAddress = localStorage.getItem(`bridge_dest_${networkId}`) || '';
        setDestinationAddress(savedAddress);
        setUseDifferentAddress(false);
        setErrors({});
        resetSubmitState();
        console.debug('[Bridge] Selected network:', networkId, 'saved address:', savedAddress);
    };

    // Format number with thousands separators for display
    const formatAmountDisplay = useCallback(value => {
        if (!value || value === '') return '';
        // Strip existing commas
        const raw = value.replace(/,/g, '');
        // Split by decimal
        const parts = raw.split('.');
        // Add thousands separators to integer part
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return parts.join('.');
    }, []);

    // Get raw amount (without commas) for calculations
    const rawAmount = amount.replace(/,/g, '');
    const handleAmountChange = e => {
        // Strip commas from input to get raw value
        const rawValue = e.target.value.replace(/,/g, '');
        // Allow only numbers and single decimal point
        if (/^\d*\.?\d*$/.test(rawValue)) {
            // Cap at max balance
            const numVal = parseFloat(rawValue) || 0;
            const maxBalance = Number.isFinite(balance) ? balance / 1_000_000 : null;
            let finalValue = rawValue;
            if (maxBalance !== null && numVal > maxBalance && maxBalance > 0) {
                finalValue = maxBalance.toFixed(6);
            }
            // Store formatted value with commas
            setAmount(formatAmountDisplay(finalValue));
            const error = validateAmount(finalValue);
            setErrors(prev => ({
                ...prev,
                amount: error
            }));
            if (submitStage !== 'idle') resetSubmitState();
        }
    };
    const handleMaxAmount = () => {
        if (!selectedNetwork || !Number.isFinite(balance)) return;
        // Fee is subtracted from amount, so MAX is full balance
        const maxAmount = Math.max(0, balance / 1_000_000);
        setAmount(formatAmountDisplay(maxAmount.toFixed(6)));
        setErrors(prev => ({
            ...prev,
            amount: null
        }));
    };
    const handleAddressChange = e => {
        const value = e.target.value;
        setDestinationAddress(value);
        // Save to localStorage for this network
        if (selectedNetwork?.id) {
            localStorage.setItem(`bridge_dest_${selectedNetwork.id}`, value);
        }
        const error = validateAddress(value);
        setErrors(prev => ({
            ...prev,
            address: error
        }));
        if (submitStage !== 'idle') resetSubmitState();
    };
    const handleSubmit = async () => {
        let stageAtError = 'submitting';
        console.debug('[Bridge] Submit attempt', {
            network: selectedNetwork?.id,
            amount: rawAmount,
            destination: effectiveDestination
        });

        // Validate all fields (use raw amount without commas)
        const amountError = validateAmount(rawAmount);
        // Only validate manual address entry
        const needsManualAddress = !selectedNetwork?.canDerive || useDifferentAddress;
        const addressError = needsManualAddress ? validateAddress(destinationAddress, true) : null;
        if (!selectedNetwork) {
            setErrors({
                network: 'Please select a destination network'
            });
            return;
        }
        if (amountError || addressError) {
            setErrors({
                amount: amountError,
                address: addressError
            });
            return;
        }
        if (!rawAmount) {
            setErrors({
                amount: 'Amount is required'
            });
            return;
        }

        // Check we have an effective destination
        if (!effectiveDestination) {
            setErrors({
                address: 'Destination address is required'
            });
            return;
        }

        // Capture pre-bridge balances and info for progress screen
        setPreBridgeMirageBalance(balance);
        setBridgeOutAmount(rawAmount);
        setBridgeOutNetwork(selectedNetwork);
        // Note: For Solana bridge out, we'll fetch the destination balance after mint completes

        setIsSubmitting(true);
        setErrors(prev => ({
            ...prev,
            submit: null
        }));
        setSubmitError('');
        setSubmitTxHash('');
        setVerificationProgress({
            attempt: 0,
            maxAttempts: 0
        });
        setErrorStage(null);
        setSubmitStage('submitting');
        stageAtError = 'submitting';
        try {
            // Convert MIRAGE to umirage (1 MIRAGE = 1,000,000 umirage)
            const amountUmirage = Math.floor(parseFloat(rawAmount) * 1_000_000);
            const result = await bridgeBurn(selectedNetwork.id, effectiveDestination, amountUmirage);
            if (!result || !result.success) {
                throw new Error(formatError(result));
            }
            const txHash = String(result.tx_hash || '').toLowerCase();
            if (!txHash) {
                throw new Error('Missing transaction hash');
            }
            setSubmitTxHash(txHash);
            console.debug('[Bridge] Transaction submitted:', txHash);
            setSubmitStage('verifying');
            stageAtError = 'verifying';
            console.debug('[Bridge] Verification poll schedule (ms):', {
                initialDelayMs: BRIDGE_POLL_SCHEDULE.initialDelayMs,
                intervalsMs: BRIDGE_POLL_SCHEDULE.intervalsMs
            });
            const pollResult = await pollTxStatus(txHash, {
                initialDelay: BRIDGE_POLL_SCHEDULE.initialDelayMs,
                intervals: BRIDGE_POLL_SCHEDULE.intervalsMs,
                requireIndexed: false,
                onProgress: ({
                    attempt,
                    maxAttempts
                }) => {
                    setVerificationProgress({
                        attempt,
                        maxAttempts
                    });
                    console.debug('[Bridge] Verification attempt', attempt, 'of', maxAttempts);
                }
            });
            if (!pollResult) throw new Error('Confirmation timeout');
            if (!pollResult.success) {
                throw new Error(pollResult.error_details?.message || 'Transaction rejected');
            }
            setSubmitStage('confirmed');
            setErrors(prev => ({
                ...prev,
                submit: null
            }));
            console.debug('[Bridge] Transaction confirmed:', txHash);

            // Keep final state visible until user starts a new bridge
        } catch (e) {
            const msg = e?.message || 'An unexpected error occurred';
            console.error('Bridge submission error:', e);
            setSubmitStage('error');
            setSubmitError(msg);
            setErrors({
                submit: msg
            });
            setErrorStage(stageAtError);
        } finally {
            setIsSubmitting(false);
        }
    };

    // Calculate preview values
    // Fee is SUBTRACTED - user pays (amount), receives (amount - fee) on destination
    const parsedAmount = parseFloat(rawAmount) || 0;
    const receiveAmount = bridgeFee !== null ? Math.max(0, parsedAmount - bridgeFee) : 0;

    // Determine if we can submit
    const needsManualAddress = !selectedNetwork?.canDerive || useDifferentAddress;
    const hasValidDestination = needsManualAddress ? destinationAddress && !errors.address : !!derivedAddress;
    const canSubmit = selectedNetwork && bridgeFee !== null &&
        // Chain must be configured with fee
        rawAmount && parseFloat(rawAmount) > 0 && hasValidDestination && !errors.amount && !isSubmitting && submitStage !== 'confirmed';
    const inputsDisabled = isSubmitting || submitStage === 'confirmed';
    const isSolanaBridge = selectedNetwork?.id === 'solana';
    const solanaCluster = useMemo(() => {
        const cluster = (chainConfigs?.solana?.solana_cluster || '').toLowerCase().trim();
        if (!cluster || cluster === 'mainnet') return '';
        return cluster;
    }, [chainConfigs]);
    const solscanClusterParam = solanaCluster ? `?cluster=${solanaCluster}` : '';

    // Format balance for display (full number with thousands separators, no decimals)
    const formatBalance = umirage => {
        if (!Number.isFinite(umirage)) return '...';
        const mirage = Math.floor(umirage / 1_000_000);
        return mirage.toLocaleString();
    };
    const stepOrder = ['submitting', 'verifying', 'confirmed'];
    const currentStepIndex = submitStage === 'error' ? stepOrder.indexOf(errorStage || 'submitting') : stepOrder.indexOf(submitStage);
    const getStepState = step => {
        if (submitStage === 'idle') return 'pending';
        const idx = stepOrder.indexOf(step);
        if (submitStage === 'error') {
            if (idx < currentStepIndex) return 'complete';
            if (idx === currentStepIndex) return 'error';
            return 'pending';
        }
        // When burn is confirmed, the Solana mint step is still pending
        if (submitStage === 'confirmed') {
            if (step === 'confirmed') {
                if (!isSolanaBridge) {
                    return 'complete';
                }
                if (mintStatus.state === 'minted') return 'complete';
                if (mintStatus.state === 'error' || mintStatus.state === 'timeout') return 'error';
                return 'active';
            }
            return 'complete';
        }
        if (idx < currentStepIndex) return 'complete';
        if (idx === currentStepIndex) return 'active';
        return 'pending';
    };

    // Format elapsed time for a step (e.g., "1.2s")
    // For completed steps, show how long they took (until next step started)
    // For active/current step, show time since it started
    const formatStepTime = step => {
        const stepStart = stepTimestamps[step];
        if (!stepStart) return '';
        const stepIdx = stepOrder.indexOf(step);
        const state = getStepState(step);

        // For completed steps, show duration (time until next step)
        if (state === 'complete' && stepIdx < stepOrder.length - 1) {
            const nextStep = stepOrder[stepIdx + 1];
            const nextStart = stepTimestamps[nextStep];
            if (nextStart) {
                const duration = (nextStart - stepStart) / 1000;
                return ` (${duration.toFixed(1)}s)`;
            }
        }

        // For the last step (confirmed/mint), use completedAt if available (works for complete, error, timeout)
        if (step === 'confirmed' && mintStatus.completedAt) {
            const duration = (mintStatus.completedAt - stepStart) / 1000;
            return ` (${duration.toFixed(1)}s)`;
        }

        // For active step or last completed step, show elapsed from start
        const elapsed = stepElapsed[step];
        if (elapsed === undefined || elapsed === null) return '';
        return ` (${elapsed.toFixed(1)}s)`;
    };
    const confirmedStepState = getStepState('confirmed');
    const showMintTimer = isSolanaBridge && (confirmedStepState === 'active' || confirmedStepState === 'complete' || confirmedStepState === 'error');
    const outboundAttestationPowerText = formatAttestationPower(outboundAttestationProgress.attestedPower, outboundAttestationProgress.requiredPower, attestationThresholdBps);
    return {
        location,
        theme,
        address,
        valoperAddress,
        activeTab,
        selectedNetwork,
        amount,
        destinationAddress,
        setDestinationAddress,
        useDifferentAddress,
        setUseDifferentAddress,
        balance,
        balanceLoading,
        balanceError,
        submitStage,
        submitError,
        submitTxHash,
        errorStage,
        errors,
        setErrors,
        stepsRef,
        mintStatus,
        outboundAttestationProgress,
        chainConfigs,
        attestationThresholdBps,
        preBridgeMirageBalance,
        bridgeOutAmount,
        bridgeOutNetwork,
        bridgeFee,
        derivedAddress,
        refreshBalance,
        handleNewBridge,
        handleTabChange,
        handleNetworkSelect,
        rawAmount,
        handleAmountChange,
        handleMaxAmount,
        handleAddressChange,
        handleSubmit,
        parsedAmount,
        receiveAmount,
        hasValidDestination,
        canSubmit,
        inputsDisabled,
        isSolanaBridge,
        solscanClusterParam,
        formatBalance,
        getStepState,
        formatStepTime,
        showMintTimer,
        outboundAttestationPowerText
    };
}