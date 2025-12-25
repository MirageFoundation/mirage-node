import React from "react";
import { useNavigate } from "react-router-dom";
import { TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";

function AuthPageShell({ activeTab, children }) {
    const navigate = useNavigate();

    const handleSelect = (tab) => {
        if (tab === activeTab) return;
        if (tab === "create") {
            navigate("/create_account");
        } else if (tab === "login") {
            navigate("/login");
        }
    };

    return (
        <TabbedContainer>
            <TabsRow role="tablist" aria-label="Account access">
                <ClickableTab
                    type="button"
                    role="tab"
                    aria-selected={activeTab === "create"}
                    $active={activeTab === "create"}
                    onClick={() => handleSelect("create")}
                >
                    Create Account
                </ClickableTab>
                <ClickableTab
                    type="button"
                    role="tab"
                    aria-selected={activeTab === "login"}
                    $active={activeTab === "login"}
                    onClick={() => handleSelect("login")}
                >
                    Sign In
                </ClickableTab>
            </TabsRow>
            <ContainerBody>
                {children}
            </ContainerBody>
        </TabbedContainer>
    );
}

export default AuthPageShell;
