#!/usr/bin/env python3
"""Analyze validation results to showcase grounding and claims identification."""

import json
import sys
from pathlib import Path

def analyze_validation_report(report_path: Path) -> None:
    """Analyze and display validation report with focus on grounding and claims."""
    
    with open(report_path, 'r') as f:
        report = json.load(f)
    
    print("=" * 80)
    print("ARTICLE VALIDATION ANALYSIS")
    print("=" * 80)
    print()
    
    # Overall results
    print("📊 OVERALL RESULTS")
    print("-" * 80)
    print(f"Status: {report.get('status', 'unknown')}")
    print(f"Decision: {report.get('decision', 'unknown')}")
    print(f"Releasable: {report.get('is_releasable', False)}")
    print(f"Processing Time: {report.get('processing_time_ms', 0)}ms")
    print()
    
    # Scores
    factual = report.get('factual', {})
    contextual = report.get('contextual', {})
    quality = report.get('quality', {})
    
    print("📈 VALIDATION SCORES")
    print("-" * 80)
    print(f"Factual:    {factual.get('score', 0):.2f} (confidence: {factual.get('confidence', 0):.2f}) {'✓' if factual.get('passed') else '✗'}")
    print(f"Contextual: {contextual.get('score', 0):.2f} (confidence: {contextual.get('confidence', 0):.2f}) {'✓' if contextual.get('passed') else '✗'}")
    print(f"Quality:    {quality.get('score', 0):.2f} (confidence: {quality.get('confidence', 0):.2f}) {'✓' if quality.get('passed') else '✗'}")
    print()
    
    # Claims identification analysis
    print("🔍 CLAIMS IDENTIFICATION & PRIORITIZATION")
    print("-" * 80)
    
    details = factual.get('details', {})
    selection = details.get('selection_counts', {})
    
    print(f"Total Claims Considered: {selection.get('considered', 0)}")
    print(f"Claims Selected for Verification: {selection.get('selected', 0)}")
    print(f"Deferred (Capacity Limit): {selection.get('deferred_capacity', 0)}")
    print(f"Deferred (Low Priority): {selection.get('deferred_low_priority', 0)}")
    print(f"Priority Threshold: {details.get('priority_threshold', 0):.2f}")
    print()
    
    # Verification results
    print("✅ VERIFICATION RESULTS")
    print("-" * 80)
    print(f"Verified Claims: {details.get('verified', 0)}")
    print(f"Contradicted Claims: {details.get('contradicted', 0)}")
    print(f"Uncertain Claims: {details.get('uncertain', 0)}")
    print(f"Errors: {details.get('errors', 0)}")
    print()
    
    # Selected claims with priority scores
    selected_claims = details.get('selected_claims', {})
    items = selected_claims.get('items', [])
    
    if items:
        print("📋 SELECTED CLAIMS (Prioritized)")
        print("-" * 80)
        for i, claim in enumerate(items, 1):
            category = claim.get('category', 'unknown')
            score = claim.get('score', 0)
            text = claim.get('text', 'N/A')
            reasons = claim.get('reasons', [])
            
            print(f"\n{i}. [{category.upper()}] Priority Score: {score:.3f}")
            print(f"   Location: {claim.get('source_field', 'unknown')} (sentence {claim.get('sentence_index', 0)})")
            print(f"   Text: {text}")
            if reasons:
                print(f"   Reasons: {', '.join(reasons)}")
        
        omitted = selected_claims.get('omitted', 0)
        if omitted > 0:
            print(f"\n   ... and {omitted} more claims (omitted from display)")
    else:
        print("📋 SELECTED CLAIMS")
        print("-" * 80)
        print("No claims were selected for verification")
    
    print()
    
    # Issues found
    issues = factual.get('issues', [])
    if issues:
        print("⚠️  FACTUAL ISSUES FOUND")
        print("-" * 80)
        for i, issue in enumerate(issues, 1):
            severity = issue.get('severity', 'unknown')
            message = issue.get('message', 'N/A')
            location = issue.get('location', 'unknown')
            suggestion = issue.get('suggestion', '')
            source_url = issue.get('source_url')
            
            print(f"\n{i}. [{severity.upper()}] {message}")
            print(f"   Location: {location}")
            if suggestion:
                print(f"   Suggestion: {suggestion}")
            if source_url:
                print(f"   Source: {source_url}")
    else:
        print("✅ NO FACTUAL ISSUES FOUND")
        print("-" * 80)
        print("All verified claims passed factual checks")
    
    print()
    print("=" * 80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_validation_results.py <report.json>")
        print("\nExample:")
        print("  python analyze_validation_results.py test_output/test_with_grounding.json")
        sys.exit(1)
    
    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(f"Error: File not found: {report_path}")
        sys.exit(1)
    
    analyze_validation_report(report_path)
