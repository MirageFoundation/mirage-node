import React from 'react';
import { PostGrid, AnimatedCard } from '../styled/Layout';
import CardView from './CardView';

export default function MoonFeedView({ posts, state, updatePost, hidingPostsSet, flashingPostsSet, viewerAddress }) {
    if (!posts || posts.length === 0) return null;

    return (
        <PostGrid>
            {posts.map((post, index) => {
                const hasValidTitle = post && typeof post.title === 'string' && post.title.trim().length > 0;
                const hasValidTopic = post && typeof post.topic === 'string' && post.topic.trim().length > 0;
                if (!hasValidTitle || !hasValidTopic || post.deleted) return null;

                if (!post?.post_id || typeof post?.author !== 'string') {
                    throw new Error('MoonFeedView: post_id/author missing');
                }
                let postTs = Number(post?.timestamp);
                if (!Number.isFinite(postTs)) {
                    throw new Error('MoonFeedView: timestamp missing');
                }
                const postKey = String(post.post_id).toLowerCase();
                const isHiding = hidingPostsSet.has(postKey);
                const isViewerPost = String(post.author).toLowerCase() === viewerAddress.toLowerCase();
                if (postTs > 1e12) postTs = Math.floor(postTs / 1000);
                const isVeryRecent = Number.isFinite(postTs) && (Math.floor(Date.now() / 1000) - postTs) <= 30;
                const isFlashing = !isHiding && (flashingPostsSet.has(postKey) || (isViewerPost && isVeryRecent));
                const animDelay = isHiding ? 0 : Math.min(index * 50, 250);

                return (
                    <AnimatedCard
                        key={post.post_id}
                        $hiding={isHiding}
                        $flash={isFlashing}
                        style={{
                            animationDelay: `${animDelay}ms`,
                        }}
                    >
                        <CardView
                            state={state}
                            post={post}
                            updatePost={updatePost}
                        />
                    </AnimatedCard>
                );
            })}
        </PostGrid>
    );
}
