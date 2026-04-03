import React from 'react';
import styled from 'styled-components';
import MobileBottomNav from './components/MobileBottomNav';

const Container = styled.div`
    width: 100%;
    margin: 0 auto;
    padding: 0 1rem;
    padding-bottom: 3rem;
    @media (max-width: 1000px) {
        padding: 0 0.25rem;
        padding-bottom: 3rem;
    }
    @media (max-width: 600px) {
        padding-bottom: 80px;
    }
`;

export default function BlueMoonShell({ children, state }) {
    return (
        <>
            <Container>{children}</Container>
            <MobileBottomNav state={state} />
        </>
    );
}
