import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Custom hook for managing tabs with URL query param sync
 * @param {string} defaultTab - The default tab to show
 * @param {string[]} validTabs - Array of valid tab names
 * @returns {[string, function]} - [activeTab, setActiveTab]
 */
export function useTabs(defaultTab, validTabs = []) {
    const [searchParams, setSearchParams] = useSearchParams();
    
    const getInitialTab = useCallback(() => {
        const urlTab = searchParams.get('tab');
        if (urlTab && validTabs.includes(urlTab)) {
            return urlTab;
        }
        return defaultTab;
    }, [searchParams, defaultTab, validTabs]);
    
    const [activeTab, setActiveTabState] = useState(getInitialTab);
    
    // Sync tab state with URL changes
    useEffect(() => {
        const urlTab = searchParams.get('tab');
        if (urlTab && validTabs.includes(urlTab) && urlTab !== activeTab) {
            setActiveTabState(urlTab);
        } else if (!urlTab && activeTab !== defaultTab) {
            // If no tab in URL, reset to default
            setActiveTabState(defaultTab);
        }
    }, [searchParams, validTabs, activeTab, defaultTab]);
    
    // Update URL when tab changes
    const setActiveTab = useCallback((newTab) => {
        if (newTab === activeTab) return;
        if (!validTabs.includes(newTab)) return;
        
        setActiveTabState(newTab);
        
        // Update URL query param
        const newParams = new URLSearchParams(searchParams);
        if (newTab === defaultTab) {
            newParams.delete('tab');
        } else {
            newParams.set('tab', newTab);
        }
        setSearchParams(newParams, { replace: true });
    }, [activeTab, validTabs, defaultTab, searchParams, setSearchParams]);
    
    return [activeTab, setActiveTab];
}

export default useTabs;

