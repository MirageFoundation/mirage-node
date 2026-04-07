import { dark, light } from './tokens';
import { Style } from './Style';
import OnyxShell from './OnyxShell';
import OnyxFeedView from './OnyxFeedView';
import OnyxVoteSection from './components/VoteSection';

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
import MobileHeader from './components/MobileHeader';
import QuestHeroCard from './components/QuestHeroCard';
import Sidebar from './components/Sidebar';
import StickerPicker from './components/StickerPicker';
import Toast from './components/Toast';
import Tooltip, { InfoIcon, tooltipStyles } from './components/Tooltip';
import TopBar, { ProfileMenuContent } from './components/TopBar';
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
import BridgeView from './routes/BridgeView';
import ChangeUsernameView from './routes/ChangeUsernameView';
import CreateAccountView from './routes/CreateAccountView';
import CreatePostView from './routes/CreatePostView';
import DiscoverView from './routes/DiscoverView';
import FollowsView from './routes/FollowsView';
import InboxView from './routes/InboxView';
import LoginView from './routes/LoginView';
import MainView from './routes/MainView';
import NetworkView from './routes/NetworkView';
import NotFoundView from './routes/NotFoundView';
import ProfileView from './routes/ProfileView';
import ReferralsView from './routes/ReferralsView';
import ReportsView from './routes/ReportsView';
import SearchResultsView from './routes/SearchResultsView';
import SettingsView from './routes/SettingsView';
import SignOutView from './routes/SignOutView';
import StatsView from './routes/StatsView';
import SubscriptionView from './routes/SubscriptionView';
import ViewPostView from './routes/ViewPostView';
import WelcomeView from './routes/WelcomeView';

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
    MobileHeader,
    QuestHeroCard,
    Sidebar,
    StickerPicker,
    Toast,
    Tooltip,
    InfoIcon,
    tooltipStyles,
    TopBar,
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
    BridgeView,
    ChangeUsernameView,
    CreateAccountView,
    CreatePostView,
    DiscoverView,
    FollowsView,
    InboxView,
    LoginView,
    MainView,
    NetworkView,
    NotFoundView,
    ProfileView,
    ReferralsView,
    ReportsView,
    SearchResultsView,
    SettingsView,
    SignOutView,
    StatsView,
    SubscriptionView,
    ViewPostView,
    WelcomeView,
};

const onyxManifest = {
    /** Stable id (Storage `theme_id`); user-facing name is `label`. */
    id: 'onyx',
    label: 'Onyx',
    description: 'Modern card-based feed',
    supportsDarkLight: true,
    dark,
    light,
    Style,
    Shell: OnyxShell,
    Feed: OnyxFeedView,
    VoteSection: OnyxVoteSection,
    components,
    routes,
    config: {
        showHeroCards: true,
        mapHomeSortMode: false,
        profileTabs: ['profile', 'submissions', 'comments', 'algo'],
        profileDefaultTab: 'profile',
        profileUsesListFeed: false,
        profileHideFilterSelect: true,
    },
};

export default onyxManifest;
