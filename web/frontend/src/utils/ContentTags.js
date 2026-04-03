import Storage from './Storage';

const TAG_ALIASES = { porn: 'adult' };

export function normalizeTag(tag) {
    const t = (tag || '').trim().toLowerCase();
    return TAG_ALIASES[t] || t;
}

function isShowTagAdultEnabled() {
    try {
        if (typeof window === 'undefined' || !window.localStorage) return false;
        const adultRaw = window.localStorage.getItem('show_tag_adult');
        if (adultRaw !== null) {
            return JSON.parse(adultRaw) === true;
        }
        // TODO: remove show_tag_porn alias once app update is fully rolled out
        const legacyRaw = window.localStorage.getItem('show_tag_porn');
        if (legacyRaw !== null) {
            return JSON.parse(legacyRaw) === true;
        }
        return false;
    } catch (_) {
        return false;
    }
}

export function getAllowedTags() {
    const tags = [];
    if (Storage.load('show_tag_sensitive', true) !== false) tags.push('sensitive');
    if (isShowTagAdultEnabled()) tags.push('adult');
    if (Storage.load('show_tag_violence', false) === true) tags.push('violence');
    if (Storage.load('show_tag_gore', false) === true) tags.push('gore');
    if (Storage.load('show_tag_death', false) === true) tags.push('death');
    return tags;
}

export function getAllowedTagsParam() {
    return getAllowedTags().join(',');
}
