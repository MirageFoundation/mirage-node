import React from "react"
import { Helmet } from 'react-helmet-async';
import styled from "styled-components"
import { useNavigate } from 'react-router-dom';
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";

const StyledMainContainer = styled.div`
    margin-top: 0.5em;
    margin-left: 1em;
    margin-right: 1em;
    padding-top: 0.1em;
    padding-bottom: 0.25em;
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    text-align: center;
    font-size: 0.75rem;
`

function SignOutView({ state, setCredentials }) {
    let navigate = useNavigate();

    React.useEffect(() => {
        seedVault.clear();
        try { Storage.remove('vault_owner'); } catch (_) { }
        setCredentials("", "", "");
        try { localStorage.removeItem('user_balance'); } catch (_) { }
        try { Storage.remove('votes'); } catch (_) { }
        try { Storage.remove('username_pending'); } catch (_) { }
        try { Storage.remove('publicKey_pending'); } catch (_) { }
        navigate("/");
    }, [navigate, setCredentials]);

    return (
        <>
            <Helmet>
                <title>Sign Out | Mirage</title>
            </Helmet>
            <StyledMainContainer>
                <div style={{ fontSize: '1.0rem', padding: '0.5rem 0' }}>Signing out…</div>
            </StyledMainContainer>
        </>
    )
}


export default SignOutView