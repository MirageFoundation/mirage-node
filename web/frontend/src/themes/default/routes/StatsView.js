/**
 * StatsView (default theme) — admin-only fleet-wide growth dashboard.
 *
 * The dashboard itself is theme-neutral and shared across all themes
 * (components/AdminStatsDashboard); this file only supplies the theme's page
 * shell so the nav/layout stays consistent.
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
