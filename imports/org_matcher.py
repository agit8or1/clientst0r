"""
Organization matching utility with fuzzy logic
"""
from difflib import SequenceMatcher
from core.models import Organization
import logging

logger = logging.getLogger('imports')


class OrganizationMatcher:
    """Match and create organizations with fuzzy name matching."""

    def __init__(self, threshold=85):
        """
        Initialize matcher.

        Args:
            threshold: Minimum similarity score (0-100) to consider a match
        """
        self.threshold = threshold

    def normalize_name(self, name):
        """
        Normalize organization name for comparison.

        - Convert to lowercase
        - Remove common suffixes (LLC, Inc, Corp, etc.)
        - Remove extra whitespace
        - Remove special characters
        """
        if not name:
            return ''

        name = name.lower().strip()

        # Remove common company suffixes
        suffixes = [
            ' llc', ' inc', ' incorporated', ' corp', ' corporation',
            ' ltd', ' limited', ' co', ' company', ' l.l.c.', ' inc.',
            ' corp.', ' ltd.', ' co.', ', llc', ', inc', ', inc.',
            ', ltd', ', ltd.', ', corp', ', corp.',
        ]
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[:- len(suffix)]

        # Remove special characters except spaces
        name = ''.join(c if c.isalnum() or c.isspace() else '' for c in name)

        # Remove extra whitespace
        name = ' '.join(name.split())

        return name

    def similarity_score(self, name1, name2):
        """
        Calculate similarity score between two organization names.

        Returns:
            Score from 0-100, where 100 is an exact match
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        if not norm1 or not norm2:
            return 0

        # Use SequenceMatcher for similarity ratio
        ratio = SequenceMatcher(None, norm1, norm2).ratio()
        return int(ratio * 100)

    def find_best_match(self, source_name):
        """
        Find the best matching existing organization.

        Args:
            source_name: Organization name from source system

        Returns:
            tuple: (Organization or None, score)
        """
        best_match = None
        best_score = 0

        # Get all existing organizations
        all_orgs = Organization.objects.all()

        for org in all_orgs:
            score = self.similarity_score(source_name, org.name)
            if score > best_score:
                best_score = score
                best_match = org

        # Only return match if above threshold
        if best_score >= self.threshold:
            return best_match, best_score
        else:
            return None, best_score

    def match_or_create(self, source_name, source_id=None, dry_run=False):
        """
        Find existing organization or create new one.

        Args:
            source_name: Organization name from source system
            source_id: Optional source system ID for logging
            dry_run: If True, don't actually create organization

        Returns:
            tuple: (Organization, was_created: bool, match_score: int or None)
        """
        # Try to find existing match
        matched_org, score = self.find_best_match(source_name)

        if matched_org:
            logger.info(f"Matched '{source_name}' to existing org '{matched_org.name}' (score: {score})")
            return matched_org, False, score

        # No match found, create new organization
        if dry_run:
            logger.info(f"[DRY RUN] Would create new organization: {source_name}")
            # In dry run, return a dummy organization (not saved)
            dummy_org = Organization(name=source_name)
            return dummy_org, True, None
        else:
            new_org = Organization.objects.create(
                name=source_name,
                description=f"Imported from {source_id}" if source_id else "Imported"
            )
            logger.info(f"Created new organization: {new_org.name} (ID: {new_org.id})")
            return new_org, True, None

    def get_all_matches(self, source_names, min_score=None):
        """
        Get match information for multiple organization names.

        Useful for preview/reporting.

        Args:
            source_names: List of organization names from source
            min_score: Minimum score to include (default: self.threshold)

        Returns:
            list of dicts with keys: source_name, matched_org, score, action
        """
        if min_score is None:
            min_score = self.threshold

        results = []
        for source_name in source_names:
            matched_org, score = self.find_best_match(source_name)

            if matched_org:
                action = 'match'
            else:
                action = 'create'

            results.append({
                'source_name': source_name,
                'matched_org': matched_org,
                'score': score,
                'action': action,
            })

        return results
