import Storage from './Storage';

export function getAllowedTags() {
    const tags = [];
    if (Storage.load('show_tag_sensitive', true) !== false) tags.push('sensitive');
    if (Storage.load('show_tag_porn', false) === true) tags.push('porn');
    if (Storage.load('show_tag_violence', false) === true) tags.push('violence');
    if (Storage.load('show_tag_gore', false) === true) tags.push('gore');
    if (Storage.load('show_tag_death', false) === true) tags.push('death');
    return tags;
}

export function getAllowedTagsParam() {
    return getAllowedTags().join(',');
}
