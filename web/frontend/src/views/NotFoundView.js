import React, { useEffect } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation, useNavigate } from 'react-router-dom';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import Button from "../components/Button";
import { ContentGrid, ModernPostFeed } from "../styled/Layout";

const NotFoundCard = styled.div`
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 2rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    align-items: center;
    text-align: center;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
    color: ${({ theme }) => theme.colors.text};

    @media (max-width: 600px) {
        padding: 1.5rem 1rem;
    }
`;

const NotFoundCode = styled.div`
    font-size: 2.5rem;
    font-weight: 700;
    letter-spacing: 0.08rem;
`;

const NotFoundTitle = styled.div`
    font-size: 1.1rem;
    font-weight: 600;
`;

const NotFoundPath = styled.div`
    font-size: 0.75rem;
    color: ${({ theme }) => theme.colors.subtleText};
    word-break: break-all;
`;

const NotFoundActions = styled.div`
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: center;
`;

function NotFoundView({ state }) {
    const location = useLocation();
    const navigate = useNavigate();
    const path = `${location.pathname}${location.search || ''}`;

    useEffect(() => {
        console.debug('[NotFoundView] 404 for route:', path);
    }, [path]);

    return (
        <ContentGrid>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <Helmet>
                    <title>404 - Mirage</title>
                </Helmet>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <NotFoundCard>
                        <NotFoundCode>404</NotFoundCode>
                        <NotFoundTitle>Page not found</NotFoundTitle>
                        <NotFoundPath>{path}</NotFoundPath>
                        <NotFoundActions>
                            <Button size="sm" onClick={() => navigate(-1)}>Go back</Button>
                            <Button size="sm" variant="subtle" to="/home">Home</Button>
                        </NotFoundActions>
                    </NotFoundCard>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

export default NotFoundView;
