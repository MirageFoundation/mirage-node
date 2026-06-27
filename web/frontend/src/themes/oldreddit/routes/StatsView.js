/**
 * StatsView (oldreddit theme) — admin-only fleet-wide growth dashboard.
 * Shared, theme-neutral dashboard rendered inside the theme's page shell.
 */
import React from "react";
import { ContentGrid } from "../Layout";
import AdminStatsDashboard from "../../../components/AdminStatsDashboard";

export default function StatsView() {
    return (
        <ContentGrid>
            <AdminStatsDashboard />
        </ContentGrid>
    );
}
