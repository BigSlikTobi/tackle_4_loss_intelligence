"""Display validation results in a clean, readable format."""

from __future__ import annotations

import json
from typing import Any, Dict, List


class ValidationResultsDisplay:
    """Formats and displays article validation results."""
    
    # ANSI color codes
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color
    
    @classmethod
    def display(cls, team_abbr: str, validation_response: Dict[str, Any]) -> None:
        """Display validation results for a team article."""
        
        print(f"\n{cls.BLUE}{'=' * 80}{cls.NC}")
        print(f"{cls.BOLD}{cls.BLUE}VALIDATION RESULTS: {team_abbr}{cls.NC}")
        print(f"{cls.BLUE}{'=' * 80}{cls.NC}\n")
        
        # Overall status
        cls._display_status(validation_response)
        
        # Factual validation
        factual = validation_response.get('factual', {})
        if factual.get('enabled'):
            cls._display_factual_validation(factual)
        
        # Contextual validation
        contextual = validation_response.get('contextual', {})
        if contextual.get('enabled'):
            cls._display_contextual_validation(contextual)
        
        # Quality validation
        quality = validation_response.get('quality', {})
        if quality.get('enabled'):
            cls._display_quality_validation(quality)
        
        # Summary
        cls._display_summary(validation_response)
        
        print(f"{cls.BLUE}{'=' * 80}{cls.NC}\n")
    
    @classmethod
    def _display_status(cls, response: Dict[str, Any]) -> None:
        """Display overall validation status."""
        status = response.get('status', 'unknown')
        decision = response.get('decision', 'unknown')
        is_releasable = response.get('is_releasable', False)
        processing_time = response.get('processing_time_ms', 0)
        
        # Color based on decision
        if decision == 'release':
            decision_color = cls.GREEN
            decision_icon = '✓'
        elif decision == 'reject':
            decision_color = cls.RED
            decision_icon = '✗'
        else:
            decision_color = cls.YELLOW
            decision_icon = '⚠'
        
        print(f"{cls.BOLD}Status:{cls.NC} {status}")
        print(f"{cls.BOLD}Decision:{cls.NC} {decision_color}{decision_icon} {decision.upper()}{cls.NC}")
        print(f"{cls.BOLD}Releasable:{cls.NC} {'Yes' if is_releasable else 'No'}")
        print(f"{cls.BOLD}Processing Time:{cls.NC} {processing_time}ms")
        print()
    
    @classmethod
    def _display_factual_validation(cls, factual: Dict[str, Any]) -> None:
        """Display factual validation results with claims analysis."""
        score = factual.get('score', 0)
        confidence = factual.get('confidence', 0)
        passed = factual.get('passed', False)
        details = factual.get('details', {})
        
        # Header
        status_icon = f"{cls.GREEN}✓{cls.NC}" if passed else f"{cls.RED}✗{cls.NC}"
        print(f"{cls.BOLD}{cls.CYAN}📊 FACTUAL VALIDATION {status_icon}{cls.NC}")
        print(f"{cls.CYAN}{'-' * 80}{cls.NC}")
        
        # Scores
        score_color = cls.GREEN if score >= 0.7 else (cls.YELLOW if score >= 0.5 else cls.RED)
        print(f"Score: {score_color}{score:.2f}{cls.NC} | Confidence: {confidence:.2f}")
        print()
        
        # Claims identification
        if details:
            cls._display_claims_identification(details)
        
        # Issues
        issues = factual.get('issues', [])
        if issues:
            cls._display_issues("Factual", issues)
        else:
            print(f"{cls.GREEN}✓ No factual issues found{cls.NC}")
        
        print()
    
    @classmethod
    def _display_claims_identification(cls, details: Dict[str, Any]) -> None:
        """Display claims identification and verification results."""
        print(f"{cls.BOLD}Claims Identification:{cls.NC}")
        
        # Summary stats
        claims_total = details.get('claims_total', 0)
        claims_checked = details.get('claims_checked', 0)
        verified = details.get('verified', 0)
        contradicted = details.get('contradicted', 0)
        uncertain = details.get('uncertain', 0)
        threshold = details.get('priority_threshold', 0.45)
        
        print(f"  Total Claims Found: {claims_total}")
        print(f"  Claims Verified: {claims_checked}")
        print(f"  Priority Threshold: {threshold:.2f}")
        print()
        
        # Verification breakdown
        print(f"  Results:")
        print(f"    {cls.GREEN}✓ Verified:{cls.NC} {verified}")
        print(f"    {cls.RED}✗ Contradicted:{cls.NC} {contradicted}")
        print(f"    {cls.YELLOW}? Uncertain:{cls.NC} {uncertain}")
        print()
        
        # Selected claims with priority scores
        selected_claims = details.get('selected_claims', {})
        items = selected_claims.get('items', [])
        
        if items:
            print(f"{cls.BOLD}  Top Priority Claims:{cls.NC}")
            for i, claim in enumerate(items[:5], 1):  # Show top 5
                category = claim.get('category', 'unknown').upper()
                score = claim.get('score', 0)
                text = claim.get('text', 'N/A')
                reasons = claim.get('reasons', [])
                
                # Color by category
                if category == 'STATISTIC':
                    cat_color = cls.CYAN
                elif category == 'EVENT':
                    cat_color = cls.BLUE
                else:
                    cat_color = cls.YELLOW
                
                # Truncate text if too long
                if len(text) > 100:
                    text = text[:97] + '...'
                
                print(f"  {i}. [{cat_color}{category}{cls.NC}] Priority: {score:.3f}")
                print(f"     {text}")
                if reasons:
                    print(f"     {cls.CYAN}↳{cls.NC} {', '.join(reasons[:2])}")
                print()
            
            omitted = selected_claims.get('omitted', 0)
            if omitted > 0:
                print(f"  ... and {omitted} more claims")
                print()
    
    @classmethod
    def _display_contextual_validation(cls, contextual: Dict[str, Any]) -> None:
        """Display contextual validation results."""
        score = contextual.get('score', 0)
        confidence = contextual.get('confidence', 0)
        passed = contextual.get('passed', False)
        
        # Header
        status_icon = f"{cls.GREEN}✓{cls.NC}" if passed else f"{cls.RED}✗{cls.NC}"
        print(f"{cls.BOLD}{cls.CYAN}🎯 CONTEXTUAL VALIDATION {status_icon}{cls.NC}")
        print(f"{cls.CYAN}{'-' * 80}{cls.NC}")
        
        # Scores
        score_color = cls.GREEN if score >= 0.7 else (cls.YELLOW if score >= 0.5 else cls.RED)
        print(f"Score: {score_color}{score:.2f}{cls.NC} | Confidence: {confidence:.2f}")
        print()
        
        # Issues
        issues = contextual.get('issues', [])
        if issues:
            cls._display_issues("Contextual", issues)
        else:
            print(f"{cls.GREEN}✓ No contextual issues found{cls.NC}")
        
        print()
    
    @classmethod
    def _display_quality_validation(cls, quality: Dict[str, Any]) -> None:
        """Display quality validation results."""
        score = quality.get('score', 0)
        confidence = quality.get('confidence', 0)
        passed = quality.get('passed', False)
        details = quality.get('details', {})
        
        # Header
        status_icon = f"{cls.GREEN}✓{cls.NC}" if passed else f"{cls.RED}✗{cls.NC}"
        print(f"{cls.BOLD}{cls.CYAN}✨ QUALITY VALIDATION {status_icon}{cls.NC}")
        print(f"{cls.CYAN}{'-' * 80}{cls.NC}")
        
        # Scores
        score_color = cls.GREEN if score >= 0.7 else (cls.YELLOW if score >= 0.5 else cls.RED)
        print(f"Score: {score_color}{score:.2f}{cls.NC} | Confidence: {confidence:.2f}")
        
        # Quality rules checked
        if details:
            rules_checked = details.get('rules_checked', 0)
            violations = details.get('violations', 0)
            errors = details.get('errors', 0)
            print(f"Rules Checked: {rules_checked} | Violations: {violations} | Errors: {errors}")
        
        print()
        
        # Issues
        issues = quality.get('issues', [])
        if issues:
            cls._display_issues("Quality", issues)
        else:
            print(f"{cls.GREEN}✓ No quality issues found{cls.NC}")
        
        print()
    
    @classmethod
    def _display_issues(cls, category: str, issues: List[Dict[str, Any]]) -> None:
        """Display validation issues, deduplicating by message."""
        if not issues:
            return
        
        # Deduplicate issues by message, keeping the highest severity
        seen_messages = {}
        severity_priority = {'critical': 3, 'warning': 2, 'info': 1, 'unknown': 0}
        
        for issue in issues:
            message = issue.get('message', 'N/A')
            severity = issue.get('severity', 'unknown')
            
            # If we've seen this message before, keep the higher severity
            if message in seen_messages:
                existing_severity = seen_messages[message].get('severity', 'unknown')
                if severity_priority.get(severity, 0) > severity_priority.get(existing_severity, 0):
                    seen_messages[message] = issue
            else:
                seen_messages[message] = issue
        
        unique_issues = list(seen_messages.values())
        
        print(f"{cls.BOLD}{category} Issues ({len(unique_issues)}):{cls.NC}")
        for i, issue in enumerate(unique_issues, 1):
            severity = issue.get('severity', 'unknown')
            message = issue.get('message', 'N/A')
            location = issue.get('location')
            suggestion = issue.get('suggestion')
            source_url = issue.get('source_url')
            
            # Color by severity
            if severity == 'critical':
                sev_color = cls.RED
                sev_icon = '🔴'
            elif severity == 'warning':
                sev_color = cls.YELLOW
                sev_icon = '⚠️'
            else:
                sev_color = cls.CYAN
                sev_icon = 'ℹ️'
            
            print(f"  {i}. {sev_icon} [{sev_color}{severity.upper()}{cls.NC}] {message}")
            
            if location:
                print(f"     Location: {location}")
            if suggestion:
                print(f"     {cls.GREEN}→{cls.NC} {suggestion}")
            if source_url:
                print(f"     Source: {source_url}")
            print()

    
    @classmethod
    def _display_summary(cls, response: Dict[str, Any]) -> None:
        """Display summary of rejection and review reasons."""
        rejection_reasons = response.get('rejection_reasons', [])
        review_reasons = response.get('review_reasons', [])
        
        # Only show summary if there are reasons to display
        if not (rejection_reasons or review_reasons):
            return
        
        print(f"{cls.BOLD}{cls.RED}📋 SUMMARY{cls.NC}")
        print(f"{cls.RED}{'-' * 80}{cls.NC}")
        
        if rejection_reasons:
            print(f"{cls.BOLD}Rejection Reasons ({len(rejection_reasons)}):{cls.NC}")
            for i, reason in enumerate(rejection_reasons, 1):
                print(f"  {i}. {cls.RED}✗{cls.NC} {reason}")
            print()
        
        if review_reasons:
            print(f"{cls.BOLD}Review Reasons ({len(review_reasons)}):{cls.NC}")
            for i, reason in enumerate(review_reasons, 1):
                print(f"  {i}. {cls.YELLOW}⚠{cls.NC} {reason}")
            print()



def display_validation_results(team_abbr: str, validation_response: Dict[str, Any]) -> None:
    """Public interface for displaying validation results."""
    ValidationResultsDisplay.display(team_abbr, validation_response)


def display_validation_results_from_json(team_abbr: str, json_str: str) -> None:
    """Parse JSON string and display validation results."""
    try:
        data = json.loads(json_str)
        display_validation_results(team_abbr, data)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        print(f"Raw response: {json_str}")
