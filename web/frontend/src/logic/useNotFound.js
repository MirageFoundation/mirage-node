import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
export function useNotFound({
  state
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const path = `${location.pathname}${location.search || ''}`;
  useEffect(() => {
    console.debug('[NotFoundView] 404 for route:', path);
  }, [path]);
  return {
    location,
    navigate,
    path
  };
}