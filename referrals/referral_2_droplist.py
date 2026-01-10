#!/usr/bin/env python3
"""
Generate airdrop list from referral analysis files.

Parses analysis files from referrals/analysis/, extracts AI recommendations.
For each referee, shows ALL upstream beneficiaries who would receive payment
(L1 direct referrer, L2, L3, etc.) and prompts for approval.

When a referee is approved, ALL beneficiaries in their upstream chain get paid.
Processes deepest referees first (L3 before L2 before L1) to show the full picture.

The output CSV lists all beneficiaries and their amounts.

Usage:
    python referrals/referral_2_droplist.py
    python referrals/referral_2_droplist.py --analysis-dir /path/to/analysis
    python referrals/referral_2_droplist.py --output referrals/airdrop_pending.csv
    python referrals/referral_2_droplist.py --auto  # Skip prompts, use AI recommendations
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ANALYSIS_DIR = SCRIPT_DIR / "analysis"
DEFAULT_OUTPUT_FILE = SCRIPT_DIR / "airdrop_pending.csv"
DB_URL = "postgresql://mirage:mirage@127.0.0.1:5432/mirage"


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class Beneficiary:
    """A beneficiary who would receive payment for a referee's activity."""

    address: str
    username: str
    level: int
    pending: float


@dataclass
class AnalysisResult:
    """Parsed data from an analysis markdown file."""

    username: str
    address: str

    # Activity
    posts: int = 0
    comments: int = 0
    active_days: int = 0
    total_words: int = 0

    # Referrer info
    referrer_username: str = ""

    # Evidence (similarity metrics)
    timing_similarity: str = ""
    topic_overlap: str = ""
    vocab_overlap: str = ""
    fingerprint_matches: List[str] = field(default_factory=list)

    # AI Analysis
    ai_verdict: str = ""
    ai_confidence: str = ""
    ai_reasoning: str = ""
    ai_recommendation: str = ""

    # All beneficiaries who would receive payment for this referee
    beneficiaries: List[Beneficiary] = field(default_factory=list)

    # Total pending reward (sum of all beneficiaries)
    @property
    def total_pending(self) -> float:
        return sum(b.pending for b in self.beneficiaries)

    # Maximum level (depth in tree)
    @property
    def max_level(self) -> int:
        return max((b.level for b in self.beneficiaries), default=0)


# =============================================================================
# DATABASE
# =============================================================================


def connect():
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("psycopg not installed. Run: pip install 'psycopg[binary]'")
    return psycopg.connect(DB_URL, autocommit=True)


def load_beneficiaries_for_referee(cur, referee_address: str) -> List[Beneficiary]:
    """Load all beneficiaries with pending rewards for a referee."""
    cur.execute(
        """
        SELECT ua.beneficiary_address, COALESCE(p.username, ua.beneficiary_address), ua.level, ua.pending
        FROM referral_user_accruals ua
        LEFT JOIN profiles p ON LOWER(p.owner) = LOWER(ua.beneficiary_address)
        WHERE LOWER(ua.referee_address) = %s AND ua.pending > 0
        ORDER BY ua.level ASC
        """,
        (referee_address.lower(),),
    )
    return [
        Beneficiary(address=row[0].lower(), username=row[1], level=row[2], pending=float(row[3]))
        for row in cur.fetchall()
    ]


def load_usernames(cur) -> Dict[str, str]:
    """Load username mapping."""
    cur.execute("SELECT LOWER(owner), username FROM profiles WHERE username IS NOT NULL AND username != ''")
    return {row[0]: row[1] for row in cur.fetchall()}


# =============================================================================
# ANALYSIS FILE PARSING
# =============================================================================


def parse_analysis_file(filepath: Path) -> Optional[AnalysisResult]:
    """Parse a referral analysis markdown file and extract key data."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)
        return None

    result = AnalysisResult(username="", address="")

    # Extract username from title: "# Referee Analysis: <username>"
    title_match = re.search(r"^# Referee Analysis: (.+)$", content, re.MULTILINE)
    if title_match:
        result.username = title_match.group(1).strip()

    # Extract address from Identity table
    addr_match = re.search(r"\| Full Address \| `([^`]+)`", content)
    if addr_match:
        result.address = addr_match.group(1).strip().lower()

    # Extract activity stats from "Activity Summary" table
    posts_match = re.search(r"\| Posts \(top-level\) \| (\d+)", content)
    if posts_match:
        result.posts = int(posts_match.group(1))

    comments_match = re.search(r"\| Comments \(replies\) \| (\d+)", content)
    if comments_match:
        result.comments = int(comments_match.group(1))

    days_match = re.search(r"\| Active Days \| (\d+)", content)
    if days_match:
        result.active_days = int(days_match.group(1))

    words_match = re.search(r"\| Total Words Written \| (\d+)", content)
    if words_match:
        result.total_words = int(words_match.group(1))

    # Extract referrer username
    referrer_match = re.search(r"## The Referrer.*?\| Username \| `([^`]+)`", content, re.DOTALL)
    if referrer_match:
        result.referrer_username = referrer_match.group(1).strip()

    # Extract similarity metrics from "Similarity Metrics: Referee vs Referrer" table
    timing_match = re.search(r"\| Timing Similarity.*?\| ([0-9.]+%)", content)
    if timing_match:
        result.timing_similarity = timing_match.group(1)

    topic_match = re.search(r"\| Topic Overlap \| ([0-9.]+%)", content)
    if topic_match:
        result.topic_overlap = topic_match.group(1)

    vocab_match = re.search(r"\| Vocabulary Overlap \| ([0-9.]+%)", content)
    if vocab_match:
        result.vocab_overlap = vocab_match.group(1)

    # Extract fingerprint matches (CRITICAL/HIGH alerts)
    fp_matches = re.findall(r"- \*\*(CRITICAL|HIGH)\*\*: ([^\n]+)", content)
    result.fingerprint_matches = [f"{severity}: {desc}" for severity, desc in fp_matches]

    # Extract AI Analysis YAML block
    yaml_match = re.search(r"```yaml\s*\n(.*?)\n```", content, re.DOTALL)
    if yaml_match:
        try:
            ai_data = yaml.safe_load(yaml_match.group(1))
            if ai_data:
                result.ai_verdict = str(ai_data.get("verdict", "")).strip()
                result.ai_confidence = str(ai_data.get("confidence", "")).strip()
                result.ai_recommendation = str(ai_data.get("recommendation", "")).strip()
                result.ai_reasoning = str(ai_data.get("reasoning", "")).strip()
        except yaml.YAMLError:
            pass

    # Fallback to regex parsing for old-format files
    if not result.ai_verdict:
        ai_section = re.search(r"## AI Analysis.*$", content, re.DOTALL)
        if ai_section:
            ai_text = ai_section.group(0)
            verdict_match = re.search(r"\*\*Verdict\*\*:\s*(.+?)(?:\n|$)", ai_text)
            if verdict_match:
                result.ai_verdict = verdict_match.group(1).strip()
            conf_match = re.search(r"\*\*Confidence\*\*:\s*(.+?)(?:\n|$)", ai_text)
            if conf_match:
                result.ai_confidence = conf_match.group(1).strip()
            reason_match = re.search(r"\*\*Reasoning\*\*:\s*\n(.+?)(?:\n\n|\*\*|$)", ai_text, re.DOTALL)
            if reason_match:
                result.ai_reasoning = reason_match.group(1).strip()
            rec_match = re.search(r"\*\*Recommendation\*\*:\s*\n?(.+?)(?:\n\n|$)", ai_text, re.DOTALL)
            if rec_match:
                result.ai_recommendation = rec_match.group(1).strip()

    return result if result.username and result.address else None


def load_all_analyses(analysis_dir: Path, cur) -> List[AnalysisResult]:
    """Load all analysis results and enrich with beneficiary data from DB."""
    results = []
    if not analysis_dir.exists():
        print(f"Warning: Analysis directory not found: {analysis_dir}", file=sys.stderr)
        return results

    for filepath in sorted(analysis_dir.glob("*.md")):
        result = parse_analysis_file(filepath)
        if result:
            # Load all beneficiaries for this referee from DB
            result.beneficiaries = load_beneficiaries_for_referee(cur, result.address)
            if result.beneficiaries:
                results.append(result)

    return results


# =============================================================================
# USER INTERFACE
# =============================================================================


def get_ai_recommendation_action(result: AnalysisResult) -> str:
    """Determine the recommended action based on AI analysis."""
    rec_lower = result.ai_recommendation.lower().strip()

    if rec_lower in ("approve", "deny", "review"):
        return rec_lower

    if "denied" in rec_lower or "deny" in rec_lower or "reject" in rec_lower:
        return "deny"
    if "approved" in rec_lower or "approve" in rec_lower:
        return "approve"
    if "review" in rec_lower or "held" in rec_lower:
        return "review"

    verdict_lower = result.ai_verdict.lower()
    if "gaming" in verdict_lower:
        return "deny"
    if "suspicious" in verdict_lower or "likely gaming" in verdict_lower:
        return "deny"
    if "real" in verdict_lower or "likely real" in verdict_lower:
        return "approve"

    return "review"


def display_analysis(result: AnalysisResult) -> None:
    """Display analysis details for a referee and ALL beneficiaries who would be paid."""
    print("\n" + "=" * 70)
    print(f"REFEREE: {result.username}")
    if result.referrer_username:
        print(f"REFERRER: {result.referrer_username}")
    print("=" * 70)
    print()

    # Activity of referee
    print("ACTIVITY")
    print(f"  Posts: {result.posts}  |  Comments: {result.comments}  |  Active Days: {result.active_days}  |  Words: {result.total_words}")
    print()

    # Key evidence
    has_evidence = result.timing_similarity or result.fingerprint_matches
    if has_evidence:
        print("KEY EVIDENCE")
        if result.timing_similarity:
            print(f"  Timing Similarity:    {result.timing_similarity}")
        if result.topic_overlap:
            print(f"  Topic Overlap:        {result.topic_overlap}")
        if result.vocab_overlap:
            print(f"  Vocabulary Overlap:   {result.vocab_overlap}")
        if result.fingerprint_matches:
            print()
            print("  Fingerprint Matches:")
            for match in result.fingerprint_matches:
                print(f"    - {match}")
        print()

    # ALL beneficiaries who would receive payment
    print("PAYMENTS IF APPROVED")
    for b in result.beneficiaries:
        print(f"  L{b.level}: {b.pending:.6f} MIRAGE -> {b.username}")
    print(f"  " + "-" * 40)
    print(f"  TOTAL: {result.total_pending:.6f} MIRAGE")
    print()

    # AI Analysis
    print("AI ANALYSIS")
    print(f"  Verdict:    {result.ai_verdict}")
    print(f"  Confidence: {result.ai_confidence}")
    print()

    if result.ai_reasoning:
        # Word wrap the reasoning for better readability
        wrapped = textwrap.fill(result.ai_reasoning, width=70, initial_indent="  ", subsequent_indent="  ")
        print(wrapped)
        print()

    if result.ai_recommendation:
        print(f"  Recommendation: {result.ai_recommendation.upper()}")
        print()


def prompt_user(result: AnalysisResult) -> str:
    """Prompt user to accept or override the AI recommendation."""
    action = get_ai_recommendation_action(result)

    green = "\033[92m"
    red = "\033[91m"
    yellow = "\033[93m"
    bold = "\033[1m"
    reset = "\033[0m"

    pay_text = f"PAY {result.total_pending:.6f} MIRAGE to {len(result.beneficiaries)} beneficiaries"
    deny_text = "DENY (block all payments)"

    if action == "approve":
        print(f"  {bold}[ENTER]{reset} {green}{pay_text}{reset}  <- AI recommends")
        print(f"  {bold}[D]{reset}     {red}{deny_text}{reset}")
    elif action == "deny":
        print(f"  {bold}[ENTER]{reset} {red}{deny_text}{reset}  <- AI recommends")
        print(f"  {bold}[P]{reset}     {green}{pay_text}{reset}")
    else:
        print(f"  {bold}[ENTER]{reset} {yellow}SKIP (needs review){reset}  <- AI recommends")
        print(f"  {bold}[P]{reset}     {green}{pay_text}{reset}")
        print(f"  {bold}[D]{reset}     {red}{deny_text}{reset}")

    print()

    while True:
        try:
            response = input("Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n\nAborted by user.")
            sys.exit(1)

        if response == "":
            # ENTER = accept AI recommendation
            return action
        elif response == "p":
            return "approve"
        elif response == "d":
            return "deny"
        else:
            print("Invalid input. Press ENTER for recommendation, P to pay, or D to deny.")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Generate airdrop list from referral analysis")
    parser.add_argument(
        "--analysis-dir",
        type=Path,
        default=DEFAULT_ANALYSIS_DIR,
        help=f"Directory containing analysis markdown files (default: {DEFAULT_ANALYSIS_DIR})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output file for airdrop list (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatically accept AI recommendations without prompting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing output file",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Referral Airdrop List Generator")
    print("=" * 60)
    print(f"Analysis dir: {args.analysis_dir}")
    print(f"Output file:  {args.output}")
    print(f"Mode:         {'Auto' if args.auto else 'Interactive'}")
    print()

    # Connect to database
    print("Connecting to database...")
    with connect() as conn:
        with conn.cursor() as cur:
            # Load analyses with beneficiary data
            print("Loading analysis files...")
            analyses = load_all_analyses(args.analysis_dir, cur)

            if not analyses:
                print("No analysis files with pending rewards found.")
                print("Run referral_1_analysis.py first.")
                sys.exit(1)

            print(f"  Found {len(analyses)} referees with pending rewards")
            print()

            # Sort by max level (deepest first) so we process L3 before L2 before L1
            # This way we see the full picture from the bottom up
            analyses.sort(key=lambda x: (-x.max_level, -x.total_pending))

            # Process each referee
            # For each decision, we store ALL beneficiaries that get paid/denied
            # (referee_username, referee_address, beneficiary_username, beneficiary_address, level, amount, status)
            decisions: List[Tuple[str, str, str, str, int, float, str]] = []
            skipped_referees: List[str] = []

            for i, result in enumerate(analyses, 1):
                print(f"\n[{i}/{len(analyses)}]", end="")
                display_analysis(result)

                action = get_ai_recommendation_action(result)

                if args.auto:
                    if action == "approve":
                        for b in result.beneficiaries:
                            decisions.append(
                                (result.username, result.address, b.username, b.address, b.level, b.pending, "approved")
                            )
                        print(
                            f"  -> AUTO APPROVED: Pay {result.total_pending:.6f} MIRAGE to {len(result.beneficiaries)} beneficiaries"
                        )
                    elif action == "deny":
                        for b in result.beneficiaries:
                            decisions.append(
                                (result.username, result.address, b.username, b.address, b.level, b.pending, "denied")
                            )
                        print(f"  -> AUTO DENIED: {result.username}")
                    else:
                        skipped_referees.append(result.username)
                        print(f"  -> AUTO SKIPPED (review needed): {result.username}")
                else:
                    final_action = prompt_user(result)

                    if final_action == "approve":
                        for b in result.beneficiaries:
                            decisions.append(
                                (result.username, result.address, b.username, b.address, b.level, b.pending, "approved")
                            )
                        print(
                            f"  -> APPROVED: Pay {result.total_pending:.6f} MIRAGE to {len(result.beneficiaries)} beneficiaries"
                        )
                    elif final_action == "deny":
                        for b in result.beneficiaries:
                            decisions.append(
                                (result.username, result.address, b.username, b.address, b.level, b.pending, "denied")
                            )
                        print(f"  -> DENIED: {result.username}")
                    else:
                        skipped_referees.append(result.username)
                        print(f"  -> SKIPPED: {result.username}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    approved = [d for d in decisions if d[6] == "approved"]
    denied = [d for d in decisions if d[6] == "denied"]

    # Aggregate by beneficiary
    beneficiary_totals: Dict[str, Tuple[str, float, List[str]]] = {}
    for referee_username, _, beneficiary_username, beneficiary_address, _, amount, status in approved:
        if beneficiary_address not in beneficiary_totals:
            beneficiary_totals[beneficiary_address] = (beneficiary_username, 0.0, [])
        name, total, referees = beneficiary_totals[beneficiary_address]
        beneficiary_totals[beneficiary_address] = (name, total + amount, referees + [referee_username])

    total_approved = sum(d[5] for d in approved)
    total_denied = sum(d[5] for d in denied)

    # Count unique referees
    approved_referees = set(d[1] for d in approved)
    denied_referees = set(d[1] for d in denied)

    print(f"Approved: {len(approved_referees)} referees ({total_approved:.6f} MIRAGE to pay)")
    print(f"Denied:   {len(denied_referees)} referees ({total_denied:.6f} MIRAGE blocked)")
    print(f"Skipped:  {len(skipped_referees)} referees (need manual review)")
    print()

    if beneficiary_totals:
        print(f"Unique beneficiaries to pay: {len(beneficiary_totals)}")
        for addr, (name, total, referees) in sorted(beneficiary_totals.items(), key=lambda x: -x[1][1]):
            print(f"  {name}: {total:.6f} MIRAGE (from {len(referees)} referee(s): {', '.join(referees)})")
        print()

    if not decisions:
        print("No decisions made. No output file written.")
        sys.exit(0)

    # Generate output CSV
    if args.dry_run:
        print("DRY RUN - Would write the following to output file:")
        print("-" * 80)
        print("referee_username,referee_address,beneficiary_username,beneficiary_address,level,amount,status")
        for d in decisions:
            print(f"{d[0]},{d[1]},{d[2]},{d[3]},{d[4]},{d[5]:.6f},{d[6]}")
        print("-" * 80)
    else:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "referee_username",
                    "referee_address",
                    "beneficiary_username",
                    "beneficiary_address",
                    "level",
                    "amount",
                    "status",
                ]
            )
            for d in decisions:
                writer.writerow([d[0], d[1], d[2], d[3], d[4], f"{d[5]:.6f}", d[6]])

        print(f"Output written to: {args.output}")
        
if __name__ == "__main__":
    main()
