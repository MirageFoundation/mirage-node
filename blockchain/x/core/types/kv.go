package types

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"
)

// Binary KV prefixes. Logical names in the upgrade plan (`c|slug`) map to these
// byte prefixes plus length-prefixed / fixed-width components. Never parse
// user-controlled delimiter-separated strings.

const (
	PfxCommunity            = "c|"
	PfxCommunitySupport     = "cc|"
	PfxCommunityFounder     = "cf|"
	PfxCommunityHistory     = "ch|"
	PfxCommunitySeq         = "communityseq"
	PfxCommunityHistNext    = "chnext|"
	PfxJoin                 = "jc|"
	PfxJoinRev              = "cj|"
	PfxJoinCount            = "jcc|"
	PfxBlockCommunity       = "bc|"
	PfxBlockCommunityIdx    = "bci|"
	PfxBlockCommunityCount  = "bcc|"
	PfxBlockCommunityNext   = "bcnext|"
	PfxCurationTeam         = "ct|"
	PfxCurationTeamNext     = "ctnext|"
	PfxCurationTeamName     = "ctname|"
	PfxCurationTeamMember   = "ctm|"
	PfxCurationTeamUser     = "ctu|"
	PfxCurationTeamUserCnt  = "ctuc|"
	PfxCurationInvite       = "cti|"
	PfxCurationInviteRev    = "ctir|"
	PfxCurationInviteCnt    = "ctirc|"
	PfxCurationTeamHist     = "cth|"
	PfxCurationTeamHistNext = "cthnext|"
	PfxCurationEligible     = "cte|"
	PfxCurationSupportOrd   = "cts|"
	PfxCurationCreated      = "ctcreated|"
	PfxHiddenPost           = "chp|"
	PfxHiddenUser           = "chu|"
	PfxThreadLock           = "chl|"
	PfxThreadLockCount      = "chlc|"
	PfxCurationPostTag      = "cpt|"
	PfxCurationPrune        = "ctp|"
	PfxCurationPruneNext    = "ctpnext"
	PfxPostMeta             = "pm|"
	PfxPostSeq              = "postseq"
	PfxVoteDir              = "vd|"
	PfxUpvoteReserved       = "vur|"
	PfxReplyReserved        = "rr|"
	PfxEngagement           = "ev|"
	PfxEngagementCount      = "evc|"
	PfxCreatorEpoch         = "ce|"
	PfxCreatorEpochOpen     = "ceopen|"
	PfxCreatorEpochSettle   = "cesettle|"
	PfxCreatorEpochDeadline = "cedeadline|"
	PfxCreatorEpochPrune    = "ceprune|"
	PfxEpochTarget          = "ect|"
	PfxTargetEpoch          = "ectarget|"
	PfxTargetTotal          = "targettotal|"
	PfxEpochCreatorAccrual  = "eca|"
	PfxCreatorEpochIdx      = "ecacreator|"
	PfxEpochClaim           = "eclaim|"
	PfxCreatorClock         = "creator_clock"
	PfxCreatorLiability     = "creator_liability"
	PfxCreatorSurplus       = "creator_activation_surplus"
	PfxCreatorSchedule      = "creator_schedule"
	PfxCreatorReset         = "creator_reset"
	// Creator fee streaming. A tranche no longer pre-splits its creator share
	// into one record per epoch it spans; it adds a per-second rate and one
	// end breakpoint, and each epoch draws its pool from the accumulator as it
	// elapses. Every creator_stream_* singleton is zeroed directly by the
	// reset, so only the breakpoint index belongs in CreatorResetPrefixes.
	PfxCreatorStream     = "creator_stream_"
	PfxCreatorStreamRate = "creator_stream_rate"
	PfxCreatorStreamAcc  = "creator_stream_acc"
	PfxCreatorStreamPaid = "creator_stream_paid"
	PfxCreatorStreamTs   = "creator_stream_ts"
	PfxCreatorStreamEnd  = "cstrend|"
	PfxTrancheSeq        = "trancheseq"
	PfxTranche           = "tranche|"
	PfxTranchePayer      = "tranchepayer|"
	PfxTrancheRecipient  = "trancherecipient|"
	PfxSubscriberQuota   = "sq|"
	PfxSubRenewalQueue   = "sr|"
	PfxSubRenewalState   = "sra|"
)

func lp(b []byte) []byte {
	if len(b) > 0xffff {
		panic("kv component exceeds uint16 length")
	}
	out := make([]byte, 2+len(b))
	binary.BigEndian.PutUint16(out[:2], uint16(len(b)))
	copy(out[2:], b)
	return out
}

func u64(v uint64) []byte {
	out := make([]byte, 8)
	binary.BigEndian.PutUint64(out, v)
	return out
}

func i64(v int64) []byte {
	return u64(uint64(v))
}

func concat(parts ...[]byte) []byte {
	n := 0
	for _, p := range parts {
		n += len(p)
	}
	out := make([]byte, 0, n)
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

func CanonicalAccBytes(addr string) ([]byte, error) {
	acc, err := sdk.AccAddressFromBech32(addr)
	if err != nil {
		return nil, fmt.Errorf("invalid address %q: %w", addr, err)
	}
	if acc.String() != addr {
		return nil, fmt.Errorf("non-canonical address %q", addr)
	}
	return acc, nil
}

func MustAcc(addr string) []byte {
	b, err := CanonicalAccBytes(addr)
	if err != nil {
		panic(err)
	}
	return b
}

func HashBytes(hexHash string) ([]byte, error) {
	h := strings.ToLower(strings.TrimSpace(hexHash))
	if len(h) != 64 {
		return nil, fmt.Errorf("hash must be 64 lowercase hex characters")
	}
	for _, c := range h {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return nil, fmt.Errorf("hash must be lowercase hex")
		}
	}
	b, err := hex.DecodeString(h)
	if err != nil {
		return nil, err
	}
	if len(b) != 32 {
		return nil, fmt.Errorf("hash decode length %d", len(b))
	}
	return b, nil
}

func KeyCommunity(slug string) []byte {
	return concat([]byte(PfxCommunity), lp([]byte(slug)))
}

func KeyCommunitySupport(slug string) []byte {
	return concat([]byte(PfxCommunitySupport), lp([]byte(slug)))
}

func KeyCommunityFounder(addr, slug string) []byte {
	return concat([]byte(PfxCommunityFounder), MustAcc(addr), lp([]byte(slug)))
}

func KeyCommunityFounderPrefix(addr string) []byte {
	return concat([]byte(PfxCommunityFounder), MustAcc(addr))
}

func KeyCommunityHistory(slug string, seq uint64) []byte {
	return concat([]byte(PfxCommunityHistory), lp([]byte(slug)), u64(seq))
}

func KeyCommunityHistNext(slug string) []byte {
	return concat([]byte(PfxCommunityHistNext), lp([]byte(slug)))
}

func KeyJoin(addr, slug string) []byte {
	return concat([]byte(PfxJoin), MustAcc(addr), lp([]byte(slug)))
}

func KeyJoinPrefix(addr string) []byte {
	return concat([]byte(PfxJoin), MustAcc(addr))
}

func KeyJoinRev(slug, addr string) []byte {
	return concat([]byte(PfxJoinRev), lp([]byte(slug)), MustAcc(addr))
}

func KeyJoinCount(addr string) []byte {
	return concat([]byte(PfxJoinCount), MustAcc(addr))
}

func KeyBlockCommunity(addr string, seq uint64, pattern string) []byte {
	return concat([]byte(PfxBlockCommunity), MustAcc(addr), u64(seq), lp([]byte(pattern)))
}

func KeyBlockCommunityPrefix(addr string) []byte {
	return concat([]byte(PfxBlockCommunity), MustAcc(addr))
}

func KeyBlockCommunityIdx(addr, pattern string) []byte {
	return concat([]byte(PfxBlockCommunityIdx), MustAcc(addr), lp([]byte(pattern)))
}

func KeyBlockCommunityCount(addr string) []byte {
	return concat([]byte(PfxBlockCommunityCount), MustAcc(addr))
}

func KeyBlockCommunityNext(addr string) []byte {
	return concat([]byte(PfxBlockCommunityNext), MustAcc(addr))
}

func KeyCurationTeam(slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationTeam), lp([]byte(slug)), u64(teamID))
}

func KeyCurationTeamPrefix(slug string) []byte {
	return concat([]byte(PfxCurationTeam), lp([]byte(slug)))
}

func KeyCurationTeamNext(slug string) []byte {
	return concat([]byte(PfxCurationTeamNext), lp([]byte(slug)))
}

func KeyCurationTeamName(slug, normalized string) []byte {
	return concat([]byte(PfxCurationTeamName), lp([]byte(slug)), lp([]byte(normalized)))
}

func KeyCurationTeamMember(slug string, teamID uint64, addr string) []byte {
	return concat([]byte(PfxCurationTeamMember), lp([]byte(slug)), u64(teamID), MustAcc(addr))
}

func KeyCurationTeamMemberPrefix(slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationTeamMember), lp([]byte(slug)), u64(teamID))
}

func KeyCurationTeamUser(addr, slug string) []byte {
	return concat([]byte(PfxCurationTeamUser), MustAcc(addr), lp([]byte(slug)))
}

func KeyCurationTeamUserPrefix(addr string) []byte {
	return concat([]byte(PfxCurationTeamUser), MustAcc(addr))
}

func KeyCurationTeamUserCount(addr string) []byte {
	return concat([]byte(PfxCurationTeamUserCnt), MustAcc(addr))
}

func KeyCurationInvite(slug string, teamID uint64, addr string) []byte {
	return concat([]byte(PfxCurationInvite), lp([]byte(slug)), u64(teamID), MustAcc(addr))
}

func KeyCurationInvitePrefix(slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationInvite), lp([]byte(slug)), u64(teamID))
}

func KeyCurationInviteRev(addr, slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationInviteRev), MustAcc(addr), lp([]byte(slug)), u64(teamID))
}

func KeyCurationInviteRevPrefix(addr string) []byte {
	return concat([]byte(PfxCurationInviteRev), MustAcc(addr))
}

func KeyCurationInviteCount(addr string) []byte {
	return concat([]byte(PfxCurationInviteCnt), MustAcc(addr))
}

func KeyCurationTeamHist(slug string, teamID, seq uint64) []byte {
	return concat([]byte(PfxCurationTeamHist), lp([]byte(slug)), u64(teamID), u64(seq))
}

func KeyCurationTeamHistNext(slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationTeamHistNext), lp([]byte(slug)), u64(teamID))
}

func KeyCurationEligible(slug string, priority, creationOrder, teamID uint64) []byte {
	return concat([]byte(PfxCurationEligible), lp([]byte(slug)), u64(priority), u64(creationOrder), u64(teamID))
}

func KeyCurationSupportOrd(slug string, invertedSupport, creationOrder, teamID uint64) []byte {
	return concat([]byte(PfxCurationSupportOrd), lp([]byte(slug)), u64(invertedSupport), u64(creationOrder), u64(teamID))
}

func KeyCurationSupportOrdPrefix(slug string) []byte {
	return concat([]byte(PfxCurationSupportOrd), lp([]byte(slug)))
}

func KeyCurationCreated(slug, addr string) []byte {
	return concat([]byte(PfxCurationCreated), lp([]byte(slug)), MustAcc(addr))
}

func KeyHiddenPost(slug string, teamID uint64, hash []byte) []byte {
	return concat([]byte(PfxHiddenPost), lp([]byte(slug)), u64(teamID), hash)
}

func KeyHiddenPostPrefix(slug string, teamID uint64) []byte {
	return concat([]byte(PfxHiddenPost), lp([]byte(slug)), u64(teamID))
}

func KeyHiddenUser(slug string, teamID uint64, addr string) []byte {
	return concat([]byte(PfxHiddenUser), lp([]byte(slug)), u64(teamID), MustAcc(addr))
}

func KeyHiddenUserPrefix(slug string, teamID uint64) []byte {
	return concat([]byte(PfxHiddenUser), lp([]byte(slug)), u64(teamID))
}

func KeyThreadLock(slug string, teamID uint64, rootHash []byte) []byte {
	return concat([]byte(PfxThreadLock), lp([]byte(slug)), u64(teamID), rootHash)
}

func KeyThreadLockPrefix(slug string, teamID uint64) []byte {
	return concat([]byte(PfxThreadLock), lp([]byte(slug)), u64(teamID))
}

// KeyThreadLockCount counts the lock windows this team has ever opened on one
// thread. It outlives the lock itself, which is why it cannot live in the
// KeyThreadLock value: that key is deleted on unlock.
func KeyThreadLockCount(slug string, teamID uint64, rootHash []byte) []byte {
	return concat([]byte(PfxThreadLockCount), lp([]byte(slug)), u64(teamID), rootHash)
}

// MaxThreadLockWindows caps how many times one team may lock one thread.
//
// The indexer keeps a closed window per lock/unlock cycle so the replies
// written during each one stay hidden, and that list has to be bounded. It
// cannot be bounded by dropping the oldest window, which would republish
// exactly what a curator hid, nor by merging windows, which would hide replies
// written while the thread was open. So the bound is enforced here instead: the
// chain refuses to open window 101, and the curator hides individual posts if
// they need more. Nothing is ever un-hidden or over-hidden to stay under it.
const MaxThreadLockWindows = 100

func KeyCurationPostTag(slug string, teamID uint64, hash []byte) []byte {
	return concat([]byte(PfxCurationPostTag), lp([]byte(slug)), u64(teamID), hash)
}

func KeyCurationPostTagPrefix(slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationPostTag), lp([]byte(slug)), u64(teamID))
}

func KeyCurationPrune(seq uint64, slug string, teamID uint64) []byte {
	return concat([]byte(PfxCurationPrune), u64(seq), lp([]byte(slug)), u64(teamID))
}

func KeyPostMeta(hash []byte) []byte {
	return concat([]byte(PfxPostMeta), hash)
}

func KeyVoteDir(voter, targetHash []byte) []byte {
	return concat([]byte(PfxVoteDir), voter, targetHash)
}

func KeyUpvoteReserved(voter, targetHash []byte) []byte {
	return concat([]byte(PfxUpvoteReserved), voter, targetHash)
}

func KeyReplyReserved(commenter, parentHash []byte) []byte {
	return concat([]byte(PfxReplyReserved), commenter, parentHash)
}

func KeyEngagement(epoch int64, actor []byte, kind byte, target []byte) []byte {
	return concat([]byte(PfxEngagement), i64(epoch), actor, []byte{kind}, target)
}

func KeyEngagementEpochPrefix(epoch int64) []byte {
	return concat([]byte(PfxEngagement), i64(epoch))
}

func KeyEngagementCount(epoch int64, actor []byte) []byte {
	return concat([]byte(PfxEngagementCount), i64(epoch), actor)
}

func KeyCreatorEpoch(epoch int64) []byte {
	return concat([]byte(PfxCreatorEpoch), i64(epoch))
}

func KeyCreatorEpochOpen(epoch int64) []byte {
	return concat([]byte(PfxCreatorEpochOpen), i64(epoch))
}

func KeyCreatorEpochSettle(epoch int64) []byte {
	return concat([]byte(PfxCreatorEpochSettle), i64(epoch))
}

func KeyCreatorEpochDeadline(deadline, epoch int64) []byte {
	return concat([]byte(PfxCreatorEpochDeadline), i64(deadline), i64(epoch))
}

func KeyCreatorEpochPrune(epoch int64) []byte {
	return concat([]byte(PfxCreatorEpochPrune), i64(epoch))
}

func KeyEpochTarget(epoch int64, target []byte) []byte {
	return concat([]byte(PfxEpochTarget), i64(epoch), target)
}

func KeyTargetEpoch(target []byte, epoch int64) []byte {
	return concat([]byte(PfxTargetEpoch), target, i64(epoch))
}

func KeyTargetTotal(target []byte) []byte {
	return concat([]byte(PfxTargetTotal), target)
}

func KeyEpochCreatorAccrual(epoch int64, creator []byte) []byte {
	return concat([]byte(PfxEpochCreatorAccrual), i64(epoch), creator)
}

func KeyEpochCreatorAccrualPrefix(epoch int64) []byte {
	return concat([]byte(PfxEpochCreatorAccrual), i64(epoch))
}

func KeyCreatorEpochIdx(creator []byte, epoch int64) []byte {
	return concat([]byte(PfxCreatorEpochIdx), creator, i64(epoch))
}

func KeyCreatorEpochIdxPrefix(creator []byte) []byte {
	return concat([]byte(PfxCreatorEpochIdx), creator)
}

func KeyEpochClaim(epoch int64, creator []byte) []byte {
	return concat([]byte(PfxEpochClaim), i64(epoch), creator)
}

func KeyTranche(id uint64) []byte {
	return concat([]byte(PfxTranche), u64(id))
}

// KeyCreatorStreamEnd orders breakpoints by the instant a tranche stops paying
// out, so the accumulator can apply them in time order with a prefix scan. The
// tranche id only disambiguates tranches expiring in the same second.
func KeyCreatorStreamEnd(endUnix int64, id uint64) []byte {
	return concat([]byte(PfxCreatorStreamEnd), i64(endUnix), u64(id))
}

func KeyTranchePayer(addr string, id uint64) []byte {
	return concat([]byte(PfxTranchePayer), MustAcc(addr), u64(id))
}

func KeyTranchePayerPrefix(addr string) []byte {
	return concat([]byte(PfxTranchePayer), MustAcc(addr))
}

func KeyTrancheRecipient(addr string, id uint64) []byte {
	return concat([]byte(PfxTrancheRecipient), MustAcc(addr), u64(id))
}

func KeyTrancheRecipientPrefix(addr string) []byte {
	return concat([]byte(PfxTrancheRecipient), MustAcc(addr))
}

func KeySubscriberQuota(addr string) []byte {
	return concat([]byte(PfxSubscriberQuota), MustAcc(addr))
}

func KeySubRenewalQueue(attemptUnix int64, addr string, expiry int64, generation uint64) []byte {
	return concat([]byte(PfxSubRenewalQueue), i64(attemptUnix), MustAcc(addr), i64(expiry), u64(generation))
}

func KeySubRenewalState(addr string) []byte {
	return concat([]byte(PfxSubRenewalState), MustAcc(addr))
}

func UTCEpoch(unix int64) int64 {
	if unix < 0 {
		return 0
	}
	return unix / SecondsPerUTCDay
}

func InvertedSupport(count uint64) uint64 {
	return ^uint64(0) - count
}

// CreatorResetPrefixes is the deterministic wipe order for a destructive
// creator-epoch interval change. Profiles, votes, posts, and active
// subscription status are not in this list.
func CreatorResetPrefixes() []string {
	return []string{
		PfxCreatorEpochOpen,
		PfxCreatorEpochSettle,
		PfxCreatorEpochDeadline,
		PfxCreatorEpochPrune,
		PfxEngagement,
		PfxEngagementCount,
		PfxEpochTarget,
		PfxTargetEpoch,
		PfxTargetTotal,
		PfxEpochCreatorAccrual,
		PfxCreatorEpochIdx,
		PfxEpochClaim,
		PfxUpvoteReserved,
		PfxReplyReserved,
		PfxTranche,
		PfxTranchePayer,
		PfxTrancheRecipient,
		PfxCreatorEpoch,
		PfxCreatorStreamEnd,
	}
}
