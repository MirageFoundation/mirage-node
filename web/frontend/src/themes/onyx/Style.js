/**
 * Onyx theme only: html/body + document-level CSS. No other theme imports this file.
 *
 * styled-components calls its helper `createGlobalStyle` (historical name: it injects rules
 * that can target `html`/`body`). That does **not** mean Mirage shares one global stylesheet
 * across themes — each theme ships its own `Style.js`. We alias the import so our code reads
 * in terms of this theme’s rules only.
 */
import { createGlobalStyle as createThemeStyleRules } from 'styled-components'

export const Style = createThemeStyleRules`
  html {
    box-sizing: border-box;
    font-family: ${({ theme }) => theme.layout.fontFamily};
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    -webkit-text-size-adjust: 100%;
    font-size: clamp(14px, 0.9vw + 0.5rem, 22px);
    min-height: 100vh;
    background-color: ${({ theme }) => theme.colors.bg};
  }

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
    color: ${({ theme }) => theme.colors.text};
    background-color: ${({ theme }) => theme.colors.bg};
    word-break: normal;
    overflow-wrap: normal;
    text-indent: 0;
  }

  @media (max-width: 600px) {
    html, body {
      padding-bottom: calc(72px + env(safe-area-inset-bottom, 0px)) !important;
      overflow-x: hidden !important;
      max-width: 100vw;
    }
  }

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
    background: ${({ theme }) => theme.colors.scrollbar};
  }

  html.theme-switching *,
  html.theme-switching *::before,
  html.theme-switching *::after {
    transition: none !important;
    animation: none !important;
  }
`
