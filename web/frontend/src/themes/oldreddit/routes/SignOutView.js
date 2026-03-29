import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { useSignOut } from "../../../logic/useSignOut";
const StyledMainContainer = styled.div`
    margin-top: 0.5em;
    margin-left: 1em;
    margin-right: 1em;
    padding-top: 0.1em;
    padding-bottom: 0.25em;
    background-color: ${({
  theme
}) => theme.colors.panel};
    text-align: center;
    font-size: 0.75rem;
`;
function SignOutView({
  state,
  setCredentials
}) {
  useSignOut({
    state,
    setCredentials
  });
  return <>
            <Helmet>
                <title>Sign Out | Mirage</title>
            </Helmet>
            <StyledMainContainer>
                <div style={{
        fontSize: '1.0rem',
        padding: '0.5rem 0'
      }}>Signing out…</div>
            </StyledMainContainer>
        </>;
}
export default SignOutView;