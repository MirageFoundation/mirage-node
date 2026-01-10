# Referral System

The referral system rewards users for inviting new members to Mirage. Rewards are based on the activity of referred users and their subsequent referrals, creating a multi-level structure.

## How It Works

1. **Share your referral link** - Found on the "Invite & Earn" page in your profile menu
2. **Earn rewards when referrals are active** - Each day a referred user posts or comments, you earn MIRAGE
3. **Multi-level rewards** - You also earn (at reduced rates) when your referrals' referrals are active

### Reward Rates

| Level | Description | Rate per Active Day |
|-------|-------------|---------------------|
| L1 | Direct referrals | 1.0 MIRAGE |
| L2 | Their referrals | 0.5 MIRAGE |
| L3 | Next level | 0.25 MIRAGE |
| L4 | Next level | 0.125 MIRAGE |
| L5 | Next level | 0.0625 MIRAGE |

**Example:** You invite Alice and Bob. Alice is active for 5 days and invites Carol, who is active for 3 days. You earn: (5 x 1) + (5 x 1) + (3 x 0.5) = **11.5 MIRAGE**

### Important Rules

- An "active day" (period) means the user posted or commented at least once that day
- **Lifetime cap of 10 active periods per referee** - Once a referee has been rewarded for 10 periods, no further rewards accrue from them
- **No self-reward** - You don't earn rewards for your own activity, only from referrals
- Rewards are pending until approved by admin
- **Sockpuppet accounts will result in suspension and loss of all rewards**

## User-Facing Features

### Referral Links

Users can find their referral links on the **Invite & Earn** page (accessible from the avatar dropdown menu).

Two link formats are provided:
- **Home page link**: `https://mirage.talk/?referrer=mirage1...`
- **Sign up link**: `https://mirage.talk/create_account?referrer=mirage1...`

The referrer parameter is captured on any page and stored in localStorage until the user creates an account.

### Invite & Earn Page (`/invite`)

Shows:
- Referral links with copy buttons
- How it works explanation with example
- Pending rewards (yellow) - not yet approved
- Approved/paid rewards (green)
- **Referral tree** with actual accrued amounts per referee
- **Next update countdown** (time until next accrual run)
- Warning about sockpuppet abuse

## Database Schema

All referral tables are prefixed with `referral_` for easy cleanup.

### `referral_links`
Stores who referred whom (immutable once set).

```sql
CREATE TABLE referral_links (
    user_address VARCHAR(64) PRIMARY KEY,
    referrer_address VARCHAR(64) NOT NULL,
    referred_at BIGINT NOT NULL,
    created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
);
```

### `referral_pending_rewards`
Pending rewards per user, accumulated by the accrual daemon.

```sql
CREATE TABLE referral_pending_rewards (
    id SERIAL PRIMARY KEY,
    user_address VARCHAR(64) NOT NULL,
    period_start BIGINT NOT NULL,
    period_end BIGINT NOT NULL,
    self_active_days INT DEFAULT 0,
    self_reward DECIMAL(20,6) DEFAULT 0,
    referral_reward DECIMAL(20,6) DEFAULT 0,
    total_pending DECIMAL(20,6) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, approved, rejected, paid
    admin_notes TEXT,
    created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
    approved_at BIGINT,
    paid_at BIGINT,
    paid_txhash VARCHAR(64),
    UNIQUE(user_address, period_start)
);
```

### `referral_user_accruals`
Tracks actual accrued amounts per beneficiary per referee.

```sql
CREATE TABLE referral_user_accruals (
    beneficiary_address VARCHAR(64) NOT NULL,
    referee_address VARCHAR(64) NOT NULL,
    level INT NOT NULL,
    pending DECIMAL(20,6) DEFAULT 0,
    paid DECIMAL(20,6) DEFAULT 0,
    last_updated BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
    PRIMARY KEY (beneficiary_address, referee_address)
);
```

### `referral_rewarded_periods`
Tracks lifetime rewarded periods per referee (for the 10-period cap).

```sql
CREATE TABLE referral_rewarded_periods (
    referee_address VARCHAR(128) PRIMARY KEY,
    rewarded_count INTEGER NOT NULL DEFAULT 0,
    last_updated BIGINT
);
```

### `referral_trust_scores`
Tracks referrer trustworthiness based on approval rate of their referrals.

```sql
CREATE TABLE referral_trust_scores (
    referrer_address VARCHAR(64) PRIMARY KEY,
    trust_score DECIMAL(5,2) DEFAULT 1.0,  -- 1.0 = neutral, <1.0 = less trusted
    total_referrals INT DEFAULT 0,
    approved_referrals INT DEFAULT 0,
    rejected_referrals INT DEFAULT 0,
    last_updated BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
);
```

### `referral_analysis`
Results from the referral analysis script for admin review.

```sql
CREATE TABLE referral_analysis (
    id SERIAL PRIMARY KEY,
    referee_address VARCHAR(64) NOT NULL,
    referrer_address VARCHAR(64) NOT NULL,
    analysis_date BIGINT NOT NULL,
    classification VARCHAR(20),  -- GAMING, SUSPICIOUS, LEGIT, INSUFFICIENT
    confidence DECIMAL(3,2),
    similarity_to_referrer DECIMAL(3,2),
    flags TEXT[],
    recommendation VARCHAR(20),  -- APPROVE, REJECT, REVIEW
    admin_decision VARCHAR(20),  -- APPROVED, REJECTED, null if pending
    decided_at BIGINT,
    UNIQUE(referee_address, analysis_date)
);
```

### `referral_state`
Daemon state tracking (last run timestamp, period configuration).

```sql
CREATE TABLE referral_state (
    key VARCHAR(64) PRIMARY KEY,
    value BIGINT NOT NULL,
    updated_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
);
```

Keys used:
- `referral_accrue_last_run` - Timestamp of last accrual run
- `referral_accrue_period` - Configured period in seconds (for UI countdown)

### `user_fingerprints`
Device fingerprints for fraud detection (used by analysis script).

```sql
CREATE TABLE user_fingerprints (
    id SERIAL PRIMARY KEY,
    user_address VARCHAR(128) NOT NULL,
    ip_hash VARCHAR(64),
    user_agent TEXT,
    user_agent_hash VARCHAR(64),
    screen_width INTEGER,
    screen_height INTEGER,
    color_depth INTEGER,
    pixel_ratio REAL,
    timezone VARCHAR(64),
    timezone_offset INTEGER,
    language VARCHAR(32),
    languages TEXT,
    platform VARCHAR(64),
    hardware_concurrency INTEGER,
    device_memory REAL,
    touch_support BOOLEAN,
    canvas_hash VARCHAR(64),
    webgl_vendor VARCHAR(128),
    webgl_renderer VARCHAR(256),
    webgl_hash VARCHAR(64),
    fingerprint_hash VARCHAR(64),
    first_seen BIGINT,
    last_seen BIGINT,
    seen_count INTEGER DEFAULT 1
);
```

## Scripts

### `referrals/referral_accrue.py`

Daemon that runs continuously, calculating pending rewards at configured intervals.

```bash
# Run as daemon (continuous loop, default 24-hour periods)
python referrals/referral_accrue.py

# Run once and exit
python referrals/referral_accrue.py --once

# Dry run (show calculations without saving)
python referrals/referral_accrue.py --dry-run

# Force immediate run (ignore last run time)
python referrals/referral_accrue.py --force

# Use custom period (for testing, e.g. 60 seconds)
python referrals/referral_accrue.py --period 60
```

The daemon:
- Runs in tmux window `referral` (started by entrypoint.sh)
- Checks activity since last run
- Calculates rewards based on referral tree with **halving per level** (L1=1.0, L2=0.5, L3=0.25, L4=0.125, L5=0.0625)
- **Enforces lifetime cap of 10 active periods per referee**
- Saves aggregate rewards to `referral_pending_rewards`
- Saves per-referee accruals to `referral_user_accruals`
- Updates `referral_rewarded_periods` for cap tracking
- Sleeps for configured period between runs (default 24 hours)
- Tracks last run time and period in `referral_state` table for resume capability and UI countdown
- Period configurable via `--period` flag (default: 24 hours)

### `referrals/referral_analysis.py`

Analyzes referral chains for sockpuppet/gaming detection. Generates **per-referee** markdown files with comprehensive analysis.

```bash
# Analyze all referrals
python referrals/referral_analysis.py

# Custom output directory
python referrals/referral_analysis.py --output-dir /path/to/output

# Analyze specific referrer only
python referrals/referral_analysis.py --referrer mirage1abc...

# Save results to database
python referrals/referral_analysis.py --save-db
```

Output: `referrals/analysis/` directory (one markdown file per referee)

Each analysis file includes:
- **Referee profile** - Full activity metrics, network analysis, content stats
- **Temporal analysis** - Hourly/daily patterns, gaps, bursts
- **Device fingerprint analysis** - Cross-account fingerprint matches (IP, canvas, WebGL)
- **Referrer profile** - Who benefits from this referee's activity
- **Similarity metrics** - Timing, topic, vocabulary, content overlap with referrer
- **Sibling analysis** - Comparison with other referees of the same referrer
- **Activity timeline** - Visual timeline showing all accounts' activity patterns
- **Gaming indicators** - Registration bursts, minimal activity, one-way support, sequential activity patterns

Classifications:
- **GAMING** - High confidence the account is fake/sockpuppet
- **SUSPICIOUS** - Multiple red flags, needs review
- **LEGIT** - Appears to be a real user
- **INSUFFICIENT** - Not enough activity to classify

### `referrals/referral_airdrop.py`

Distributes approved referral rewards via the faucet account.

```bash
# Use default export file (referrals/airdrop_pending.txt)
python referrals/referral_airdrop.py

# Custom file with default amount fallback
python referrals/referral_airdrop.py rewards.txt 0

# Dry run
python referrals/referral_airdrop.py --dry-run

# Custom backend
python referrals/referral_airdrop.py --backend https://mirage.talk
```

File format (one entry per line):
```
# Comments start with #
username1              # Uses default amount (if specified)
username2 5.5          # Uses specific amount (5.5 MIRAGE)
username3 3.25         # Uses specific amount (3.25 MIRAGE)
```

The script:
- Reads from `referrals/airdrop_pending.txt` by default
- Resolves usernames to addresses via the backend API
- Sends tokens from the `faucet` keyring account
- Confirms each transaction before proceeding to the next
- Uses unordered transactions with 60s timeout
- Aborts on first failure to prevent double-sends

### `scripts/classify_users.py`

General user classification for sockpuppet detection (not referral-specific).

```bash
# Analyze all users, output to /tmp/mirage-classification/
python scripts/classify_users.py

# Custom output directory
python scripts/classify_users.py --output-dir /path/to/output
```

Generates per-user markdown files with:
- Classification (REAL/SUSPICIOUS/FAKE)
- Activity metrics
- Temporal patterns
- Network analysis
- Similarity to other users (sockpuppet detection)

## Admin Features

### Admin Menu

Admins (user_level >= 100) see additional menu items in the avatar dropdown:
- **Reports** - Content moderation
- **Referrals** - Referral management

### Referrals Admin Page (`/admin/referrals`)

Lists all referrers with:
- Trust score (based on approval rate)
- Total referees
- Approved/rejected/pending counts

Click a referrer to see their referees with:
- Classification and confidence
- Similarity to referrer
- Flags (high similarity, untrusted referrer, abandoned account, etc.)
- Approve/Reject buttons

**Export button** downloads approved rewards as a file for `referral_airdrop.py`.

### Admin API Endpoints

```
GET  /api/admin/referral/referrers              - List all referrers with trust scores
GET  /api/admin/referral/referrer/<addr>/referees - Get referees for a referrer with analysis
POST /api/admin/referral/decide                 - Approve/reject a referee
GET  /api/admin/referral/export                 - Export approved rewards for airdrop
```

### User API Endpoint

```
GET /api/referral/stats?address=<addr>          - Get user's referral stats and tree
```

Returns:
- `total_pending` - Total pending rewards
- `total_paid` - Total paid rewards
- `total_referrals` - Count of all referrals (all levels)
- `referral_tree` - Nested tree with actual accrued amounts per referee
- `next_update_at` - Timestamp of next accrual run (for countdown)

## Frontend Components

### Files Modified/Created

- `web/frontend/src/views/InviteView.js` - Invite & Earn page with referral tree
- `web/frontend/src/views/AdminReferralsView.js` - Admin referral management
- `web/frontend/src/components/TopBar.js` - Added menu items
- `web/frontend/src/App.js` - Added routes, referrer capture on all pages
- `web/frontend/src/utils/TransactionHandler.js` - Include referrer in account creation

### Backend Files Modified

- `web/backend/routes/public.py` - Added referral API endpoints
- `web/backend/routes/core.py` - Store referral on account creation
- `indexer/database.py` - Added referral tables

## Cleanup

To remove the referral system entirely:

```sql
DROP TABLE IF EXISTS referral_links, referral_pending_rewards, 
                     referral_trust_scores, referral_analysis, referral_state,
                     referral_user_accruals, referral_rewarded_periods;
```

Then remove the referral-related code from frontend/backend.
