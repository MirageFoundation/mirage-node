import React from "react";
import { useNavigate } from "react-router-dom";
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";
export function useSignOut({
  state,
  setCredentials
}) {
  let navigate = useNavigate();
  React.useEffect(() => {
    seedVault.clear();
    Storage.clear();
    setCredentials("", "", "");
    navigate("/");
  }, [navigate, setCredentials]);
  return {};
}