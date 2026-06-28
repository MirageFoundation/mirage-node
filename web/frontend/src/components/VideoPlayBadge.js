import React from "react";

// Centered play-triangle overlay that marks a still poster as a video preview,
// so a video thumbnail isn't mistaken for an image. Pure absolute-positioned
// overlay — the parent element must be position: relative.
export default function VideoPlayBadge({ size = 32 }) {
    const icon = Math.round(size * 0.45);
    return (
        <span
            aria-hidden="true"
            style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                width: size,
                height: size,
                borderRadius: "50%",
                background: "rgba(0, 0, 0, 0.55)",
                border: "1px solid rgba(255, 255, 255, 0.85)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                pointerEvents: "none",
                boxShadow: "0 1px 4px rgba(0, 0, 0, 0.4)",
            }}
        >
            <svg width={icon} height={icon} viewBox="0 0 24 24" fill="#ffffff" aria-hidden="true">
                <path d="M8 5v14l11-7z" />
            </svg>
        </span>
    );
}
