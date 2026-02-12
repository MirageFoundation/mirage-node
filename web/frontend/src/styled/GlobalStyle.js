import { createGlobalStyle } from 'styled-components'

//overscroll-behavior: contain; 
//https://stackoverflow.com/questions/29008194/disabling-androids-chrome-pull-down-to-refresh-feature

export const GlobalStyle = createGlobalStyle`

  /* Base resets and responsive typography */
  /* Root font-size scaled to ~90% of original (14px base instead of 16px) */
  /* This makes the entire UI more compact without changing any component code */
  html {
    box-sizing: border-box;
    font-family: 'Noto Sans';
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    -webkit-text-size-adjust: 100%;
    font-size: clamp(14px, 0.9vw + 0.5rem, 22px);
    min-height: 100vh;
    background-color: 
      ${({ theme }) => (theme && theme.colors && theme.colors.bg) ? theme.colors.bg : '#1A1A1A'};
  }

  /* Bump root size by ~10% on mobile/tablet without changing component code */
  @media (max-width: 1000px) {
    html { font-size: 130%; }
  }

  *, *::before, *::after {
    box-sizing: inherit;
  }

  html *, body, body * {
    margin: 0;
    padding: 0;
    line-height: 1.35;
  }

  body {    
    min-height: 100vh;
    color: 
      ${({ theme }) => (theme && theme.colors && theme.colors.text) ? theme.colors.text : '#FFFFFF'};
    background-color: 
      ${({ theme }) => (theme && theme.colors && theme.colors.bg) ? theme.colors.bg : '#1A1A1A'};
    word-break: normal;      /* do not break words into pieces */
    overflow-wrap: normal;   /* wrap only at normal break points (spaces) */
    text-indent: 0;
  }

  /* Add bottom padding on mobile for bottom navigation bar */
  @media (max-width: 600px) {
    html, body {
      /* 72px nav height (56px + extra buffer) + safe area inset for notched devices */
      padding-bottom: calc(72px + env(safe-area-inset-bottom, 0px)) !important;
      /* Prevent horizontal scroll caused by fixed elements */
      overflow-x: hidden !important;
      max-width: 100vw;
    }
  }
  
  /* Media should never overflow */
  img, video {
    max-width: 100%;
    height: auto;
    display: block;
  }
  
  &::-webkit-scrollbar {
    width: 0.25em;
    direction: rtl;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    background: 
      ${({ theme }) => (theme && theme.colors && theme.colors.scrollbar) ? theme.colors.scrollbar : '#CCCCCC'};
  }

  /* When switching theme, temporarily disable transitions to avoid mass flashing */
  html.theme-switching *,
  html.theme-switching *::before,
  html.theme-switching *::after {
    transition: none !important;
    animation: none !important;
  }
`
