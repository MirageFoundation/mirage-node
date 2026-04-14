import React, { useEffect, useRef } from 'react';

export default function ObservedCard({
    CardComponent,
    postId,
    observePost,
    unobservePost,
    children,
    ...rest
}) {
    if (!CardComponent) {
        throw new Error('ObservedCard: CardComponent is required');
    }

    const ref = useRef(null);
    useEffect(() => {
        const el = ref.current;
        if (el) observePost(el);
        return () => { if (el) unobservePost(el); };
    }, [observePost, unobservePost]);

    return (
        <CardComponent ref={ref} data-post-id={postId} {...rest}>
            {children}
        </CardComponent>
    );
}
