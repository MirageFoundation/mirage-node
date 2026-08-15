const FAQ_MARKDOWN = __MIRAGE_FAQ_MARKDOWN__;

if (typeof FAQ_MARKDOWN !== 'string' || FAQ_MARKDOWN.trim() === '') {
    throw new Error('FAQ markdown was not embedded. Check docs/FAQ.md and vite.config.js.');
}

export default FAQ_MARKDOWN;
