import { dark, light } from './tokens';
import { Style } from './Style';
import OldRedditShell from './OldRedditShell';
import ListFeedView from './ListFeedView';
import OldRedditVoteSection from './components/VoteSection';

import AuthPageShell from './components/AuthPageShell';
import Button from './components/Button';
import CardView from './components/CardView';
import FilterBar from './components/FilterBar';
import GifPicker from './components/GifPicker';
import InlineMedia from './components/InlineMedia';
import MarkdownEditor from './components/MarkdownEditor';
import MarkdownRenderer from './components/MarkdownRenderer';
import MediaGallery from './components/MediaGallery';
import MobileBottomNav from './components/MobileBottomNav';
import StickerPicker from './components/StickerPicker';
import Toast from './components/Toast';
import Tooltip, { InfoIcon, tooltipStyles } from './components/Tooltip';
import { ProfileMenuContent } from './components/TopBar';
import TopicSelector from './components/TopicSelector';
import UnlockPrompt from './components/UnlockPrompt';
import {
    MediaRow,
    MediaIconButton,
    MediaPreviewWrapper,
    MediaPreviewImage,
    MediaSpinner,
    MediaRemoveButton,
} from './components/MediaAttachmentLayout';

import AgentsView from './routes/AgentsView';
import BlocksView from './routes/BlocksView';
import ChangeUsernameView from './routes/ChangeUsernameView';
import CreateAccountView from './routes/CreateAccountView';
import CreatePostView from './routes/CreatePostView';
import DiscoverView from './routes/DiscoverView';
import FAQView from '../default/routes/FAQView';
import FollowsView from './routes/FollowsView';
import InboxView from './routes/InboxView';
import LoginView from './routes/LoginView';
import MainView from './routes/MainView';
import NetworkView from './routes/NetworkView';
import NotFoundView from './routes/NotFoundView';
import ProfileView from './routes/ProfileView';
import ReportsView from './routes/ReportsView';
import SearchResultsView from './routes/SearchResultsView';
import SettingsView from './routes/SettingsView';
import SignOutView from './routes/SignOutView';
import StatsView from './routes/StatsView';
import SubscriptionView from './routes/SubscriptionView';
import ViewPostView from './routes/ViewPostView';
import WelcomeView from './routes/WelcomeView';

const NullComponent = () => null;

/** Themed UI implementations keyed by name (used by theme routes + `useThemeComponent`). @see ../../components/README.md */
const components = {
    AuthPageShell,
    Button,
    CardView,
    FilterBar,
    GifPicker,
    InlineMedia,
    MarkdownEditor,
    MarkdownRenderer,
    MediaGallery,
    MobileBottomNav,
    MobileHeader: NullComponent,
    Sidebar: NullComponent,
    StickerPicker,
    Toast,
    Tooltip,
    InfoIcon,
    tooltipStyles,
    TopBar: NullComponent,
    ProfileMenuContent,
    TopicSelector,
    UnlockPrompt,
    MediaRow,
    MediaIconButton,
    MediaPreviewWrapper,
    MediaPreviewImage,
    MediaSpinner,
    MediaRemoveButton,
};

const routes = {
    AgentsView,
    BlocksView,
    ChangeUsernameView,
    CreateAccountView,
    CreatePostView,
    DiscoverView,
    FAQView,
    FollowsView,
    InboxView,
    LoginView,
    MainView,
    NetworkView,
    NotFoundView,
    ProfileView,
    ReportsView,
    SearchResultsView,
    SettingsView,
    SignOutView,
    StatsView,
    SubscriptionView,
    ViewPostView,
    WelcomeView,
};

const oldredditManifest = {
    id: 'oldreddit',
    label: 'Classic',
    description: 'Compact list-based feed (old Reddit style)',
    supportsDarkLight: true,
    dark,
    light,
    Style,
    Shell: OldRedditShell,
    Feed: ListFeedView,
    VoteSection: OldRedditVoteSection,
    components,
    routes,
    config: {
        showHeroCards: false,
        mapHomeSortMode: true,
        profileTabs: ['profile', 'submissions', 'comments', 'algo'],
        profileDefaultTab: 'profile',
        profileUsesListFeed: true,
        profileHideFilterSelect: true,
    },
};

export default oldredditManifest;
